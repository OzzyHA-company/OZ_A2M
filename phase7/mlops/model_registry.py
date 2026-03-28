"""
OZ_A2M ML Model Registry
Phase 7: Model Serving Infrastructure

Features:
- Model versioning
- A/B testing support
- Model metadata management
- Automatic model loading
"""

import os
import json
import hashlib
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class ModelMetadata:
    """Model metadata structure."""
    name: str
    version: str
    framework: str  # pytorch, tensorflow, sklearn, etc.
    description: str
    metrics: Dict[str, float]
    tags: List[str]
    created_at: str
    author: str
    hash: str
    status: str = "staging"  # staging, production, archived
    deployed_at: Optional[str] = None


class ModelRegistry:
    """
    OZ_A2M Model Registry for managing ML models.

    Directory structure:
    /models/
      ├── registry.json          # Central registry
      ├── {model_name}/
      │   ├── v1.0.0/
      │   │   ├── model.pkl
      │   │   └── metadata.json
      │   └── v1.1.0/
      │       ├── model.pkl
      │       └── metadata.json
      └── staging/
          └── current/           # Symlink to current staging model
    """

    def __init__(self, base_path: str = "/home/ozzy-claw/OZ_A2M/phase7/mlops/models"):
        self.base_path = Path(base_path)
        self.registry_file = self.base_path / "registry.json"
        self._ensure_directories()
        self._load_registry()

    def _ensure_directories(self):
        """Create necessary directories."""
        self.base_path.mkdir(parents=True, exist_ok=True)
        (self.base_path / "staging").mkdir(exist_ok=True)
        (self.base_path / "production").mkdir(exist_ok=True)

    def _load_registry(self):
        """Load or create registry."""
        if self.registry_file.exists():
            with open(self.registry_file, 'r') as f:
                self.registry = json.load(f)
        else:
            self.registry = {
                "models": {},
                "deployments": {},
                "created_at": datetime.now().isoformat()
            }
            self._save_registry()

    def _save_registry(self):
        """Save registry to disk."""
        with open(self.registry_file, 'w') as f:
            json.dump(self.registry, f, indent=2)

    def _calculate_hash(self, file_path: Path) -> str:
        """Calculate SHA256 hash of model file."""
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()

    def register_model(
        self,
        name: str,
        version: str,
        model_path: str,
        framework: str,
        description: str = "",
        metrics: Dict[str, float] = None,
        tags: List[str] = None,
        author: str = "system"
    ) -> ModelMetadata:
        """Register a new model version."""
        model_path = Path(model_path)
        if not model_path.exists():
            raise FileNotFoundError(f"Model file not found: {model_path}")

        # Create version directory
        version_dir = self.base_path / name / version
        version_dir.mkdir(parents=True, exist_ok=True)

        # Copy model file
        dest_path = version_dir / model_path.name
        shutil.copy2(model_path, dest_path)

        # Calculate hash
        model_hash = self._calculate_hash(dest_path)

        # Create metadata
        metadata = ModelMetadata(
            name=name,
            version=version,
            framework=framework,
            description=description,
            metrics=metrics or {},
            tags=tags or [],
            created_at=datetime.now().isoformat(),
            author=author,
            hash=model_hash
        )

        # Save metadata
        metadata_path = version_dir / "metadata.json"
        with open(metadata_path, 'w') as f:
            json.dump(asdict(metadata), f, indent=2)

        # Update registry
        if name not in self.registry["models"]:
            self.registry["models"][name] = {
                "versions": [],
                "latest": version,
                "production": None
            }

        self.registry["models"][name]["versions"].append(version)
        self.registry["models"][name]["latest"] = version
        self._save_registry()

        logger.info(f"Registered model {name} version {version}")
        return metadata

    def get_model(self, name: str, version: Optional[str] = None) -> Optional[Path]:
        """Get path to model file."""
        if name not in self.registry["models"]:
            return None

        if version is None:
            version = self.registry["models"][name]["latest"]

        model_dir = self.base_path / name / version
        if not model_dir.exists():
            return None

        # Find model file
        for ext in ['.pkl', '.pt', '.h5', '.onnx', '.joblib']:
            model_file = model_dir / f"model{ext}"
            if model_file.exists():
                return model_file

        return None

    def get_metadata(self, name: str, version: str) -> Optional[ModelMetadata]:
        """Get model metadata."""
        metadata_path = self.base_path / name / version / "metadata.json"
        if not metadata_path.exists():
            return None

        with open(metadata_path, 'r') as f:
            data = json.load(f)
            return ModelMetadata(**data)

    def deploy_to_staging(self, name: str, version: str):
        """Deploy model to staging environment."""
        model_path = self.get_model(name, version)
        if not model_path:
            raise ValueError(f"Model {name}:{version} not found")

        metadata = self.get_metadata(name, version)
        metadata.status = "staging"
        metadata.deployed_at = datetime.now().isoformat()

        # Update metadata
        metadata_path = self.base_path / name / version / "metadata.json"
        with open(metadata_path, 'w') as f:
            json.dump(asdict(metadata), f, indent=2)

        # Create staging symlink
        staging_link = self.base_path / "staging" / name
        if staging_link.exists():
            staging_link.unlink()
        staging_link.symlink_to(self.base_path / name / version)

        self.registry["deployments"][f"staging:{name}"] = version
        self._save_registry()

        logger.info(f"Deployed {name}:{version} to staging")

    def deploy_to_production(self, name: str, version: str):
        """Deploy model to production environment."""
        model_path = self.get_model(name, version)
        if not model_path:
            raise ValueError(f"Model {name}:{version} not found")

        metadata = self.get_metadata(name, version)
        metadata.status = "production"
        metadata.deployed_at = datetime.now().isoformat()

        # Update metadata
        metadata_path = self.base_path / name / version / "metadata.json"
        with open(metadata_path, 'w') as f:
            json.dump(asdict(metadata), f, indent=2)

        # Update production symlink
        prod_link = self.base_path / "production" / name
        if prod_link.exists():
            prod_link.unlink()
        prod_link.symlink_to(self.base_path / name / version)

        # Update registry
        self.registry["models"][name]["production"] = version
        self.registry["deployments"][f"production:{name}"] = version
        self._save_registry()

        logger.info(f"Deployed {name}:{version} to production")

    def list_models(self) -> List[str]:
        """List all registered models."""
        return list(self.registry["models"].keys())

    def list_versions(self, name: str) -> List[str]:
        """List all versions of a model."""
        if name not in self.registry["models"]:
            return []
        return self.registry["models"][name]["versions"]

    def compare_models(self, name: str, version1: str, version2: str) -> Dict:
        """Compare two model versions."""
        meta1 = self.get_metadata(name, version1)
        meta2 = self.get_metadata(name, version2)

        if not meta1 or not meta2:
            raise ValueError("One or both versions not found")

        return {
            "version1": asdict(meta1),
            "version2": asdict(meta2),
            "metrics_diff": {
                k: meta2.metrics.get(k, 0) - meta1.metrics.get(k, 0)
                for k in set(meta1.metrics) | set(meta2.metrics)
            }
        }

    def delete_model(self, name: str, version: str):
        """Delete a model version."""
        version_dir = self.base_path / name / version
        if version_dir.exists():
            shutil.rmtree(version_dir)

        # Update registry
        if name in self.registry["models"]:
            versions = self.registry["models"][name]["versions"]
            if version in versions:
                versions.remove(version)
                if not versions:
                    del self.registry["models"][name]
                self._save_registry()

        logger.info(f"Deleted model {name}:{version}")


# Global registry instance
_registry = None

def get_registry() -> ModelRegistry:
    """Get or create global model registry."""
    global _registry
    if _registry is None:
        _registry = ModelRegistry()
    return _registry


if __name__ == "__main__":
    # Test the registry
    registry = get_registry()
    print(f"Registered models: {registry.list_models()}")
