from fastapi import FastAPI

app = FastAPI(title="FixScribe")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
