"""
Slime Learning Curve API for OZ_A2M
Tracks AI/ML model learning progress and performance metrics
"""
from fastapi import APIRouter, Query
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime, timedelta
import json
import os

router = APIRouter(prefix="/slime", tags=["slime"])

SLIME_DATA_FILE = "/home/ozzy-claw/logs/slime-learning.jsonl"

class LearningPoint(BaseModel):
    timestamp: str
    episode: int
    reward: float
    loss: float
    accuracy: float
    exploration_rate: float

class LearningCurveResponse(BaseModel):
    model: str
    timeframe: str
    episodes: int
    data: List[LearningPoint]

class ModelMetrics(BaseModel):
    model_name: str
    total_episodes: int
    avg_reward: float
    best_reward: float
    convergence_episode: Optional[int]
    current_accuracy: float
    status: str  # training, converged, deployed

def ensure_slime_data():
    """Generate sample learning data if not exists"""
    os.makedirs(os.path.dirname(SLIME_DATA_FILE), exist_ok=True)

    if not os.path.exists(SLIME_DATA_FILE):
        data = []
        for episode in range(1, 101):
            # Simulate learning curve: starts low, improves over time
            progress = episode / 100
            base_reward = -50 + (progress * 100)  # -50 to +50
            noise = (episode % 10) - 5  # Random noise

            data.append({
                "timestamp": (datetime.now() - timedelta(hours=100-episode)).isoformat(),
                "episode": episode,
                "reward": round(base_reward + noise, 2),
                "loss": round(1.0 - (progress * 0.9), 4),  # 1.0 to 0.1
                "accuracy": round(50 + (progress * 45), 2),  # 50% to 95%
                "exploration_rate": round(1.0 - (progress * 0.95), 4),  # 1.0 to 0.05
            })

        with open(SLIME_DATA_FILE, "w") as f:
            for entry in data:
                f.write(json.dumps(entry) + "\n")

def read_learning_data() -> List[dict]:
    """Read learning curve data"""
    ensure_slime_data()
    data = []
    try:
        with open(SLIME_DATA_FILE, "r") as f:
            for line in f:
                if line.strip():
                    data.append(json.loads(line))
    except Exception:
        pass
    return data

@router.get("/learning-curve/{model}")
async def get_learning_curve(
    model: str,
    episodes: int = Query(default=100, ge=10, le=10000)
):
    """
    Get learning curve data for a specific model

    Available models:
    - trading_bot: Main trading bot RL model
    - risk_manager: Risk assessment model
    - market_predictor: Price prediction model
    """
    data = read_learning_data()

    # Take last N episodes
    recent_data = data[-episodes:] if len(data) > episodes else data

    learning_points = [
        LearningPoint(
            timestamp=d["timestamp"],
            episode=d["episode"],
            reward=d["reward"],
            loss=d["loss"],
            accuracy=d["accuracy"],
            exploration_rate=d["exploration_rate"]
        )
        for d in recent_data
    ]

    return LearningCurveResponse(
        model=model,
        timeframe=f"{episodes} episodes",
        episodes=len(learning_points),
        data=learning_points
    )

@router.get("/metrics/{model}")
async def get_model_metrics(model: str):
    """Get current model performance metrics"""
    data = read_learning_data()

    if not data:
        return ModelMetrics(
            model_name=model,
            total_episodes=0,
            avg_reward=0,
            best_reward=0,
            convergence_episode=None,
            current_accuracy=0,
            status="not_started"
        )

    rewards = [d["reward"] for d in data]
    accuracies = [d["accuracy"] for d in data]

    # Find convergence (when accuracy > 90% for 10 consecutive episodes)
    convergence_episode = None
    for i in range(len(data) - 10):
        if all(d["accuracy"] > 90 for d in data[i:i+10]):
            convergence_episode = data[i]["episode"]
            break

    return ModelMetrics(
        model_name=model,
        total_episodes=len(data),
        avg_reward=round(sum(rewards) / len(rewards), 2),
        best_reward=round(max(rewards), 2),
        convergence_episode=convergence_episode,
        current_accuracy=round(accuracies[-1], 2) if accuracies else 0,
        status="converged" if convergence_episode else "training"
    )

@router.get("/models")
async def get_available_models():
    """Get list of available models"""
    return {
        "models": [
            {
                "id": "trading_bot",
                "name": "Trading Bot RL",
                "type": "reinforcement_learning",
                "description": "Main trading decision model"
            },
            {
                "id": "risk_manager",
                "name": "Risk Manager",
                "type": "supervised_learning",
                "description": "Position sizing and risk assessment"
            },
            {
                "id": "market_predictor",
                "name": "Market Predictor",
                "type": "time_series",
                "description": "Price movement prediction"
            }
        ]
    }

@router.post("/record")
async def record_learning_step(
    episode: int,
    reward: float,
    loss: float,
    accuracy: float,
    model: str = "trading_bot"
):
    """Record a new learning step (called by training loop)"""
    entry = {
        "timestamp": datetime.now().isoformat(),
        "episode": episode,
        "reward": reward,
        "loss": loss,
        "accuracy": accuracy,
        "exploration_rate": max(0.05, 1.0 - (episode / 1000))
    }

    ensure_slime_data()
    with open(SLIME_DATA_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")

    return {"status": "recorded", "episode": episode}
