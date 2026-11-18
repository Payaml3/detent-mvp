"""Set up an organisation ready for decisions: rule set, fixture counterparties, an API key."""

from __future__ import annotations

from dataclasses import dataclass

from conftest import OrgFixture, make_org
from detent.api.auth import issue_key
from detent.clock import FrozenClock
from detent.domain.roles import Role
from detent.intents.registry import seed_registry
from detent.policy.schema import load_ruleset
from detent.policy.store import install_ruleset
from detent.settings import REPO_ROOT
from sqlalchemy import Engine

PEPPER = "test-pepper-abcdef123456"
POLICY_TEXT = (REPO_ROOT / "fixtures" / "policy" / "default-policy.yaml").read_text()
ALL_SCOPES = ["read", "intents:create", "exceptions:approve", "admin"]


@dataclass
class DecisionOrg:
    org: OrgFixture
    key: str
    wallets: dict[str, str]

    @property
    def id(self) -> str:
        return self.org.id

    def auth(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.key}"}


def setup_decision_org(
    engine: Engine,
    clock: FrozenClock,
    *,
    fail_safe: str = "manual_queue",
    mode: str = "auto",
    scopes: list[str] | None = None,
) -> DecisionOrg:
    org = make_org(engine, clock)
    with engine.begin() as conn:
        from sqlalchemy import text

        conn.execute(
            text(
                "UPDATE organisations SET fail_safe=:f, mode=:m, registered_name=:n, registered_account=:a "
                "WHERE org_id=:o"
            ),
            {
                "f": fail_safe,
                "m": mode,
                "n": "Demo Platform Ltd (fictional)",
                "a": "0x00000000000000000000000000000000PLATF0RM",
                "o": org.id,
            },
        )
        install_ruleset(conn, clock, org.id, load_ruleset(POLICY_TEXT), proposed_by="system:seed")
        wallets = seed_registry(conn, clock, org.id)
        key = issue_key(conn, clock, org.id, org.users[Role.PAYMENTS_LEAD], scopes or ALL_SCOPES, PEPPER)
    return DecisionOrg(org, key, wallets)


def payout(cpt: str, amount: str, currency: str, dest: dict[str, str], **kw: object) -> dict[str, object]:
    body: dict[str, object] = {
        "kind": "payout",
        "source": "platform",
        "counterparty_id": cpt,
        "destination": dest,
        "amount": {"amount": amount, "currency": currency},
    }
    body.update(kw)
    return body
