from fastapi import FastAPI
from pydantic import BaseModel


app = FastAPI(title="fyp-ml-api")


class PredictionInput(BaseModel):
    age: int
    monthly_spend: float
    support_tickets: int = 0


@app.get("/")
def root():
    return {"app": "fyp-ml-api", "status": "ready"}


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.post("/predict")
def predict(payload: PredictionInput):
    score = (payload.monthly_spend / 100.0) + (payload.support_tickets * 0.15) - (payload.age * 0.01)
    label = "high_value" if score >= 1.0 else "standard"
    return {
        "label": label,
        "score": round(score, 3),
        "model": "deterministic-demo-v1",
    }
