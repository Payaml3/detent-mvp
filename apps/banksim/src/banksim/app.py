"""banksim: stub until M3 (spec/06-rails-and-faults.md). Serves /healthz so `make dev` can start it."""

from fastapi import FastAPI

app = FastAPI(title="Detent banksim (stub, test only)")


@app.get("/healthz")
def healthz() -> dict[str, object]:
    return {"status": "ok", "stub": True}
