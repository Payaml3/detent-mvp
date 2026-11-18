"""RAL-01 and RAL-02: the shared contract suite, run against every adapter (the local EVM rail in S2).

Error normalisation: a request that never reached the rail is TECHNICAL_RETRYABLE; one that might
have reached it is TIMEOUT, never a failure.
"""

from __future__ import annotations

import contextlib
import dataclasses
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from chain_helpers import balance, needs_chain, new_wallet
from detent import devchain
from detent.domain.money import Money
from detent.domain.states import FailureClass
from detent.rails.base import AttemptView, IntentView, RailAdapter, RailError
from detent.rails.evm import EvmAdapter
from detent.rails.signer import LocalKeySigner
from detent.settings import TestNetworkGuardError

pytestmark = needs_chain


@pytest.fixture(params=["local-evm"])
def adapter(request: pytest.FixtureRequest, chain: devchain.LocalChain) -> tuple[RailAdapter, str]:
    sender, key = new_wallet(chain, usdc_minor=1_000 * 10**6)
    return (
        EvmAdapter(
            rail_id="local-evm",
            rpc_url=chain.rpc_url,
            expected_chain_id=31337,
            token_address=chain.usdc_address,
            signer=LocalKeySigner(key),
            confirmations=1,
        ),
        sender,
    )


def intent(payee: str, amount: str = "5.00", network: str = "local-evm") -> IntentView:
    return IntentView(
        payment_id="pay_CONTRACT",
        amount=Money.parse(amount, "USDC"),
        network=network,
        destination_address=payee,
    )


def view(payee: str, nonce: int | None = None, amount: str = "5.00") -> AttemptView:
    return AttemptView(
        attempt_id="att_C",
        payment_id="pay_CONTRACT",
        attempt_no=1,
        rail_id="local-evm",
        idempotency_key="pay_CONTRACT",
        amount=Money.parse(amount, "USDC"),
        destination_address=payee,
        nonce=nonce,
        raw_tx=None,
        tx_hash=None,
    )


def test_eligible_quote_health(adapter: tuple[RailAdapter, str], chain: devchain.LocalChain) -> None:
    a, _ = adapter
    payee, _ = new_wallet(chain, eth_wei=0)
    assert a.eligible(intent(payee)).eligible
    assert not a.eligible(intent(payee, network="eth-sepolia")).eligible
    assert not a.eligible(intent(payee, amount="5000.00")).eligible  # more than the wallet holds
    q = a.quote(intent(payee))
    assert isinstance(q.fee_minor, int) and q.expected_seconds >= 0
    h = a.health()
    assert h.ok and h.balance == Money.parse("1000.00", "USDC")


def test_prepare_submit_status(adapter: tuple[RailAdapter, str], chain: devchain.LocalChain) -> None:
    a, _sender = adapter
    payee, _ = new_wallet(chain, eth_wei=0)
    assert isinstance(a, EvmAdapter)
    p = a.prepare(view(payee), nonce=a.pending_nonce())
    v = view(payee, nonce=p.nonce)
    v = dataclasses.replace(v, raw_tx=p.raw_tx, tx_hash=p.tx_hash)
    assert a.status(v).state == "NOT_FOUND"  # signed, not yet broadcast
    res = a.submit(v)
    assert res.rail_reference == p.tx_hash
    st = a.status(v)
    assert st.state == "CONFIRMED" and st.confirmations >= 1
    assert balance(chain, payee) == 5_000_000
    # Re-broadcasting the same signed transaction is the same transaction: no second transfer.
    with contextlib.suppress(RailError):
        a.submit(v)
    assert balance(chain, payee) == 5_000_000


def test_explorer_link() -> None:
    a = EvmAdapter.__new__(EvmAdapter)
    a.explorer_tx_url = "https://sepolia.basescan.org/tx/{tx}"
    assert a.explorer_url("0xabc") == "https://sepolia.basescan.org/tx/0xabc"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def test_unreachable_rpc_is_retryable(chain: devchain.LocalChain) -> None:
    _, key = new_wallet(chain)
    a = EvmAdapter(
        rail_id="local-evm",
        rpc_url=f"http://127.0.0.1:{_free_port()}",
        expected_chain_id=31337,
        token_address=chain.usdc_address,
        signer=LocalKeySigner(key),
        confirmations=1,
        check_chain=False,
    )
    with pytest.raises(RailError) as ei:
        a.submit(
            AttemptView(
                "att_x",
                "pay_x",
                1,
                "local-evm",
                "pay_x",
                Money.parse("1.00", "USDC"),
                "0x" + "1" * 40,
                0,
                "0x02",
                "0x" + "ab" * 32,
            )
        )
    assert ei.value.failure_class is FailureClass.TECHNICAL_RETRYABLE


class _Slow(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        time.sleep(2)
        self.send_response(200)
        self.end_headers()

    def log_message(self, *a: object) -> None:
        pass


def test_no_answer_after_sending_is_timeout_not_failure(chain: devchain.LocalChain) -> None:
    srv = HTTPServer(("127.0.0.1", 0), _Slow)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    _, key = new_wallet(chain)
    a = EvmAdapter(
        rail_id="local-evm",
        rpc_url=f"http://127.0.0.1:{srv.server_address[1]}",
        expected_chain_id=31337,
        token_address=chain.usdc_address,
        signer=LocalKeySigner(key),
        confirmations=1,
        check_chain=False,
        timeout_seconds=0.5,
    )
    try:
        with pytest.raises(RailError) as ei:
            a.submit(
                AttemptView(
                    "att_x",
                    "pay_x",
                    1,
                    "local-evm",
                    "pay_x",
                    Money.parse("1.00", "USDC"),
                    "0x" + "1" * 40,
                    0,
                    "0x02",
                    "0x" + "ab" * 32,
                )
            )
        assert ei.value.failure_class is FailureClass.TIMEOUT
    finally:
        srv.shutdown()


def test_adapter_refuses_a_non_test_chain(chain: devchain.LocalChain) -> None:
    _, key = new_wallet(chain)
    with pytest.raises(TestNetworkGuardError):
        EvmAdapter(
            rail_id="x",
            rpc_url=chain.rpc_url,
            expected_chain_id=1,
            token_address=chain.usdc_address,
            signer=LocalKeySigner(key),
            confirmations=1,
        )
