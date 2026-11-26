"""ERC-20 USDC rail on an EVM test network (RAL-02): local anvil, Base Sepolia or Ethereum Sepolia.

Sending is two steps so the nonce and the signed bytes are stored before anything leaves (EXE-04):
``prepare`` estimates gas, checks it, and signs; ``submit`` broadcasts the stored raw transaction.
Re-broadcasting the same raw transaction is the same transaction, never a second payment.

The adapter refuses any chain outside the test networks (invariant 14).
"""

from __future__ import annotations

from typing import Any

import requests

from detent.domain.money import Currency, Money
from detent.domain.states import FailureClass
from detent.rails.base import (
    AttemptView,
    Eligibility,
    Health,
    IntentView,
    ObservedTransfer,
    Prepared,
    Quote,
    RailError,
    Resolved,
    StatusResult,
    SubmitResult,
)
from detent.rails.signer import Signer
from detent.settings import TESTNET_CHAIN_IDS, TestNetworkGuardError

ERC20_ABI: list[dict[str, Any]] = [
    {"type": "function", "name": "transfer", "stateMutability": "nonpayable",
     "inputs": [{"name": "to", "type": "address"}, {"name": "amount", "type": "uint256"}],
     "outputs": [{"name": "", "type": "bool"}]},
    {"type": "function", "name": "balanceOf", "stateMutability": "view",
     "inputs": [{"name": "who", "type": "address"}], "outputs": [{"name": "", "type": "uint256"}]},
]  # fmt: skip

GAS_HEADROOM_PERCENT = 20  # sign with 20% more gas than estimated
_NOT_REACHED = (
    "Connection refused",
    "NewConnectionError",
    "Failed to establish",
    "Name or service not known",
)


def classify(exc: BaseException) -> FailureClass:
    """Spec/06 rule of thumb: only an error that proves the request never reached the node is retryable."""
    if isinstance(exc, RailError):
        return exc.failure_class
    if isinstance(exc, requests.exceptions.ConnectTimeout):
        return FailureClass.TECHNICAL_RETRYABLE
    if isinstance(exc, requests.exceptions.ConnectionError) and any(s in str(exc) for s in _NOT_REACHED):
        return FailureClass.TECHNICAL_RETRYABLE
    return FailureClass.TIMEOUT


class EvmAdapter:
    def __init__(
        self,
        *,
        rail_id: str,
        rpc_url: str,
        expected_chain_id: int,
        token_address: str,
        signer: Signer,
        confirmations: int,
        explorer_tx_url: str | None = None,
        timeout_seconds: float = 10.0,
        check_chain: bool = True,
        expected_seconds: int = 2,
    ) -> None:
        from web3 import Web3

        if expected_chain_id not in TESTNET_CHAIN_IDS:
            raise TestNetworkGuardError(f"rail {rail_id}: chain {expected_chain_id} is not a test network")
        self.rail_id = rail_id
        self.chain_id = expected_chain_id
        self.confirmations = confirmations
        self.explorer_tx_url = explorer_tx_url
        self.expected_seconds = expected_seconds
        self._signer = signer
        self._rpc_url = rpc_url
        self._timeout = timeout_seconds
        self._http = requests.Session()
        self._w3 = Web3(
            Web3.HTTPProvider(
                rpc_url, request_kwargs={"timeout": timeout_seconds}, exception_retry_configuration=None
            )
        )
        self._token = self._w3.eth.contract(address=Web3.to_checksum_address(token_address), abi=ERC20_ABI)
        if check_chain:
            actual = int(self._w3.eth.chain_id)
            if actual != expected_chain_id:
                raise TestNetworkGuardError(
                    f"rail {rail_id}: RPC reports chain {actual}, expected {expected_chain_id}"
                )

    # ------------------------------------------------------------------------------ helpers
    @property
    def from_address(self) -> str:
        return self._signer.address

    def _usdc(self, minor: int) -> Money:
        return Money(minor, Currency.USDC)

    def _transfer_call(self, to: str, amount: Money) -> Any:
        from web3 import Web3

        if amount.currency is not Currency.USDC:
            raise RailError(FailureClass.TECHNICAL_FINAL, f"{self.rail_id} carries USDC only")
        return self._token.functions.transfer(Web3.to_checksum_address(to), amount.amount_minor)

    def explorer_url(self, tx_hash: str) -> str | None:
        return self.explorer_tx_url.format(tx=tx_hash) if self.explorer_tx_url else None

    def pending_nonce(self) -> int:
        return int(self._w3.eth.get_transaction_count(self.from_address, "pending"))

    def _gas(self, call: Any) -> tuple[int, int]:
        gas = int(call.estimate_gas({"from": self.from_address}))
        gas = gas * (100 + GAS_HEADROOM_PERCENT) // 100
        price = int(self._w3.eth.gas_price)
        return gas, price

    # ------------------------------------------------------------------------------ contract
    def eligible(self, intent: IntentView) -> Eligibility:  # noqa: PLR0911 - one return per reason
        if intent.amount.currency is not Currency.USDC:
            return Eligibility(False, "CURRENCY_NOT_SUPPORTED")
        if intent.network != self.rail_id:
            return Eligibility(False, "NETWORK_MISMATCH")
        if not intent.destination_address:
            return Eligibility(False, "NO_DESTINATION_ADDRESS")
        try:
            token = int(self._token.functions.balanceOf(self.from_address).call())
            if token < intent.amount.amount_minor:
                return Eligibility(False, "INSUFFICIENT_BALANCE")
            gas, price = self._gas(self._transfer_call(intent.destination_address, intent.amount))
            if int(self._w3.eth.get_balance(self.from_address)) < gas * price:
                return Eligibility(False, "INSUFFICIENT_GAS")
        except Exception as exc:  # cannot tell: not eligible now (the caller holds the payment)
            return Eligibility(False, f"RAIL_UNAVAILABLE:{type(exc).__name__}")
        return Eligibility(True)

    def quote(self, intent: IntentView) -> Quote:
        gas, price = self._gas(
            self._transfer_call(intent.destination_address or self.from_address, intent.amount)
        )
        return Quote(fee_minor=gas * price, fee_currency="wei", expected_seconds=self.expected_seconds)

    def prepare(self, attempt: AttemptView, nonce: int) -> Prepared:
        if not attempt.destination_address:
            raise RailError(FailureClass.TECHNICAL_FINAL, "no destination address")
        try:
            call = self._transfer_call(attempt.destination_address, attempt.amount)
            gas, price = self._gas(call)
            tx = call.build_transaction(
                {
                    "from": self.from_address,
                    "nonce": nonce,
                    "gas": gas,
                    "gasPrice": price,
                    "chainId": self.chain_id,
                }
            )
        except RailError:
            raise
        except Exception as exc:  # nothing has been broadcast yet: known not executed
            raise RailError(
                FailureClass.TECHNICAL_RETRYABLE, f"prepare failed: {type(exc).__name__}"
            ) from exc
        raw, h = self._signer.sign(tx)
        return Prepared(nonce=nonce, raw_tx=raw, tx_hash=h, from_address=self.from_address)

    def submit(self, attempt: AttemptView) -> SubmitResult:
        if not attempt.raw_tx or not attempt.tx_hash:
            raise RailError(FailureClass.TECHNICAL_FINAL, "attempt has no signed transaction")
        self._broadcast(attempt.raw_tx, attempt.tx_hash, attempt.attempt_id)
        return SubmitResult(attempt.tx_hash)

    def _broadcast(self, raw_tx: str, tx_hash: str, attempt_id: str) -> None:
        """eth_sendRawTransaction, sent directly so the attempt ID travels with it (fault logs, RAL-05)."""
        body: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "eth_sendRawTransaction",
            "params": [raw_tx],
        }
        try:
            r = self._http.post(
                self._rpc_url, json=body, timeout=self._timeout, headers={"X-DekernAI-Attempt": attempt_id}
            )
        except requests.exceptions.RequestException as exc:
            raise RailError(classify(exc), f"broadcast: {type(exc).__name__}") from exc
        if r.status_code == 503:
            # Spec/06: 503 before acceptance means the rail never took it.
            raise RailError(FailureClass.TECHNICAL_RETRYABLE, "broadcast: 503 before acceptance")
        if r.status_code >= 500:
            raise RailError(FailureClass.TIMEOUT, f"broadcast: HTTP {r.status_code}; outcome unknown")
        try:
            answer = r.json()
        except ValueError as exc:
            raise RailError(FailureClass.TIMEOUT, "broadcast: unreadable answer; outcome unknown") from exc
        if "error" in answer:
            # The node answered with an RPC error. If it already knows this exact transaction, it is sent.
            if self._knows(tx_hash):
                return
            raise RailError(
                FailureClass.TECHNICAL_RETRYABLE, f"broadcast rejected: {str(answer['error'])[:200]}"
            )

    def resolve(self, attempt: AttemptView) -> Resolved:  # noqa: PLR0911 - one return per rule in spec/06
        """EXE-06 for an UNKNOWN attempt (spec/06 UNKNOWN resolution). Reads only, except that a transaction
        the node has never seen is re-broadcast: the same signed bytes, never a new transaction."""
        assert attempt.tx_hash
        assert attempt.nonce is not None
        try:
            st = self.status(attempt)
        except RailError:
            return Resolved("UNKNOWN", {"note": "rail did not answer"})
        if st.state in ("CONFIRMED", "FAILED"):
            return Resolved(st.state, st.evidence, st.failure_class)
        if st.state == "PENDING":
            return Resolved("UNKNOWN", {"note": "transaction known to the node, not yet confirmed"})
        # NOT_FOUND: the node has never seen our transaction.
        try:
            latest = int(self._w3.eth.get_transaction_count(self.from_address, "latest"))
            pending = int(self._w3.eth.get_transaction_count(self.from_address, "pending"))
        except Exception:
            return Resolved("UNKNOWN", {"note": "rail did not answer"})
        if latest > attempt.nonce:
            return Resolved(
                "FAILED",
                {
                    "tx_hash": attempt.tx_hash,
                    "nonce": attempt.nonce,
                    "latest_nonce": latest,
                    "note": "nonce consumed by another transaction",
                },
                FailureClass.TECHNICAL_FINAL,
            )
        if pending <= attempt.nonce and attempt.raw_tx:
            return Resolved("UNKNOWN", {"note": "never reached the node"}, rebroadcast=True)
        return Resolved("UNKNOWN", {"note": "waiting"})

    def sign_replacement(self, attempt: AttemptView, gas_price_multiplier: int = 2) -> tuple[str, str]:
        """Cancel-by-replacement (EXE-06): a zero-value transfer to ourselves with the same nonce and a higher
        fee. Signed here and stored by the caller before ``broadcast_raw``; whichever transaction lands
        decides the outcome, read from the chain."""
        assert attempt.nonce is not None
        price = int(self._w3.eth.gas_price) * gas_price_multiplier
        tx = {
            "from": self.from_address,
            "to": self.from_address,
            "value": 0,
            "nonce": attempt.nonce,
            "gas": 21000,
            "gasPrice": price,
            "chainId": self.chain_id,
        }
        return self._signer.sign(tx)

    def broadcast_raw(self, raw_tx: str, tx_hash: str, attempt_id: str) -> None:
        self._broadcast(raw_tx, tx_hash, attempt_id)

    def _knows(self, tx_hash: str) -> bool:
        try:
            self._w3.eth.get_transaction(tx_hash)
            return True
        except Exception:
            return False

    def status(self, attempt: AttemptView) -> StatusResult:
        if not attempt.tx_hash:
            return StatusResult("NOT_FOUND")
        try:
            rcpt = self._w3.eth.get_transaction_receipt(attempt.tx_hash)
        except Exception as exc:
            if type(exc).__name__ == "TransactionNotFound":
                return StatusResult("PENDING") if self._knows(attempt.tx_hash) else StatusResult("NOT_FOUND")
            raise RailError(classify(exc), f"status: {type(exc).__name__}") from exc
        head = int(self._w3.eth.block_number)
        confs = head - int(rcpt["blockNumber"]) + 1
        ev = {
            "tx_hash": attempt.tx_hash,
            "block": int(rcpt["blockNumber"]),
            "confirmations": confs,
            "receipt_status": int(rcpt["status"]),
        }
        if int(rcpt["status"]) == 0:
            return StatusResult("FAILED", FailureClass.TECHNICAL_FINAL, confs, ev)
        if confs >= self.confirmations:
            return StatusResult("CONFIRMED", None, confs, ev)
        return StatusResult("PENDING", None, confs, ev)

    def health(self) -> Health:
        try:
            bal = int(self._token.functions.balanceOf(self.from_address).call())
            native = int(self._w3.eth.get_balance(self.from_address))
        except Exception as exc:
            return Health(False, None, {"error": type(exc).__name__})
        return Health(True, self._usdc(bal), {"native_wei": str(native), "from": self.from_address})

    # ------------------------------------------------------------------------------ watching (LED-04)
    TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

    def head_block(self) -> int:
        return int(self._w3.eth.block_number)

    def transfers(
        self, from_block: int, to_block: int, *, to_addresses: list[str], from_addresses: list[str]
    ) -> list[ObservedTransfer]:
        """Token Transfer logs into the watched deposit addresses and out of our sending wallets."""

        def topic(addr: str) -> str:
            return "0x" + "0" * 24 + addr.lower().removeprefix("0x")

        head = self.head_block()
        out: list[ObservedTransfer] = []
        for direction, addrs, pos in (("in", to_addresses, 2), ("out", from_addresses, 1)):
            if not addrs:
                continue
            topics: list[Any] = [self.TRANSFER_TOPIC, None, None]
            topics[pos] = [topic(a) for a in addrs]
            logs = self._w3.eth.get_logs(
                {
                    "address": self._token.address,
                    "fromBlock": from_block,
                    "toBlock": to_block,
                    "topics": topics,
                }
            )
            for lg in logs:
                t = [h.hex() if hasattr(h, "hex") else str(h) for h in lg["topics"]]
                frm = "0x" + t[1][-40:]
                to = "0x" + t[2][-40:]
                data = lg["data"]
                amount = int(data.hex() if hasattr(data, "hex") else data, 16)
                tx = lg["transactionHash"]
                txh = tx.hex() if hasattr(tx, "hex") else str(tx)
                txh = txh if txh.startswith("0x") else "0x" + txh
                blk = int(lg["blockNumber"])
                out.append(
                    ObservedTransfer(
                        external_id=f"{txh}:{int(lg['logIndex'])}",
                        tx_hash=txh,
                        log_index=int(lg["logIndex"]),
                        direction=direction,
                        from_party=frm,
                        to_party=to,
                        amount_minor=amount,
                        block_number=blk,
                        confirmations=head - blk + 1,
                    )
                )
        return out
