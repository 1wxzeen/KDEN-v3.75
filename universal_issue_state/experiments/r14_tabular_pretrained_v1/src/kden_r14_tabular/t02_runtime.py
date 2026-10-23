"""Owner-only environment/download preparation; offline pinned runtime probe."""
from __future__ import annotations

import importlib.metadata as metadata
import json
import os
import platform
import subprocess
import sys
import tempfile
import time
import urllib.request
import venv
import socket
from contextlib import contextmanager
from pathlib import Path

from .common import ContractError, atomic_json, digest, hash_file, inside, read_json, signed, verify_record


@contextmanager
def no_network():
    """Fail closed if any third-party loader tries network access during probe."""
    original_connect, original_connection = socket.socket.connect, socket.create_connection
    def denied(*args, **kwargs):
        raise ContractError("network access forbidden during offline native inference")
    socket.socket.connect = denied
    socket.create_connection = denied
    try:
        yield
    finally:
        socket.socket.connect, socket.create_connection = original_connect, original_connection


def probe_code_identity(experiment):
    return {p: hash_file(inside(experiment, p)) for p in ["src/kden_r14_tabular/t02_runtime.py", "config/checkpoints.json"]}


def checkpoint_config(experiment):
    cfg = read_json(inside(experiment, "config/checkpoints.json"))
    if digest(cfg) != "5507e5c36ee63a4bf12b597ed5ede89b9f323ae8f389727a7155dac7a6fedd84":
        raise ContractError("checkpoint/native recipe differs from the specified release")
    return cfg


def cache_environment(experiment, *, offline=True):
    env = dict(os.environ)
    for key, rel in {"PIP_CACHE_DIR": ".cache/pip", "HF_HOME": ".cache/huggingface",
                     "TORCH_HOME": ".cache/torch", "XDG_CACHE_HOME": ".cache/xdg",
                     "TMPDIR": ".cache/tmp"}.items():
        path = inside(experiment, rel); path.mkdir(parents=True, exist_ok=True)
        env[key] = str(path)
    env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONNOUSERSITE="1",
               PYTORCH_ENABLE_MPS_FALLBACK="0", HF_HUB_DISABLE_TELEMETRY="1")
    # An inherited PYTHONPATH must not introduce packages from other projects.
    env.pop("PYTHONPATH", None)
    if offline:
        env.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    else:
        env.pop("HF_HUB_OFFLINE", None); env.pop("TRANSFORMERS_OFFLINE", None)
    return env


def packages():
    result = {}
    for dist in metadata.distributions():
        name = dist.metadata["Name"].lower().replace("_", "-")
        if name in result:
            raise ContractError("duplicate installed distribution: " + name)
        result[name] = dist.version
    return dict(sorted(result.items()))


def require_local_environment(experiment):
    expected = inside(experiment, ".venv").resolve()
    if Path(sys.prefix).resolve() != expected or sys.prefix == sys.base_prefix:
        raise ContractError("use this experiment's .venv/bin/python, not the acquisition environment")
    if sys.version_info[:2] != (3, 12):
        raise ContractError("T02 reference environment requires Python 3.12")
    for dist in metadata.distributions():
        try:
            Path(dist.locate_file("")).resolve().relative_to(expected)
        except ValueError as exc:
            raise ContractError("distribution outside isolated environment") from exc


def prepare_environment(experiment):
    """Invoked by the owner, never by an acceptance/preflight command."""
    if sys.version_info[:2] != (3, 12):
        raise ContractError("create the isolated environment with the existing Python 3.12")
    if inside(experiment, "manifests/T02_PASS.json").exists():
        raise ContractError("T02 is accepted; preparation may not mutate its environment")
    receipt = inside(experiment, "environment/installation.json")
    if receipt.exists():
        verify_record(read_json(receipt))
        return {"status": "ALREADY_PREPARED", "next": "run the offline runtime probe with the experiment Python"}
    lock = inside(experiment, "runs/T02_PREPARATION.lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise ContractError("preparation lock exists; use recover-t02-lock after confirming its process is dead") from exc
    with os.fdopen(fd, "w") as stream:
        json.dump({"pid": os.getpid(), "run_id": "environment-preparation"}, stream)
    try:
        root = inside(experiment, ".venv")
        if not root.exists():
            venv.EnvBuilder(with_pip=True, system_site_packages=False).create(root)
        py = root / "bin/python"
        env = cache_environment(experiment, offline=False)
        report = inside(experiment, "environment/pip-install-report.json")
        subprocess.run([str(py), "-I", "-m", "pip", "install", "--report", str(report),
                        "-r", str(inside(experiment, "environment/requirements-t02.txt"))], check=True, env=env)
        subprocess.run([str(py), "-I", "-m", "pip", "check"], check=True, env=env)
        code = "import json,importlib.metadata as m;print(json.dumps({d.metadata['Name'].lower().replace('_','-'):d.version for d in m.distributions()},sort_keys=True))"
        installed = json.loads(subprocess.check_output([str(py), "-I", "-c", code], env=env, text=True))
        cfg = checkpoint_config(experiment)
        for model in cfg["models"]:
            if installed.get(model["package"]) != model["version"]:
                raise ContractError("installed neural package version disagrees with plan")
        frozen = "".join(f"{name}=={version}\n" for name, version in sorted(installed.items()))
        # Complete platform-specific transitive version lock, not just two top-level names.
        path = inside(experiment, "environment/requirements-resolved.txt")
        if path.exists() and path.read_text() != frozen:
            raise ContractError("an existing dependency lock differs; do not overwrite it")
        if not path.exists():
            with path.open("x") as stream:
                stream.write(frozen)
        body = {"status": "PREPARED", "python": platform.python_version(), "machine": platform.machine(),
                "system": platform.system(), "packages": installed,
                "requirements_input_sha256": hash_file(inside(experiment, "environment/requirements-t02.txt")),
                "requirements_resolved_sha256": hash_file(path), "pip_install_report_sha256": hash_file(report),
                "preparation_has_network_access": True, "model_fits_performed": 0}
        atomic_json(receipt, signed(body), immutable=True)
        return body
    finally:
        lock.unlink(missing_ok=True)


def download_checkpoints(experiment):
    if inside(experiment, "manifests/T02_PASS.json").exists():
        raise ContractError("T02 is accepted; checkpoint preparation is closed")
    cfg = checkpoint_config(experiment)
    results = []
    # Only this explicit owner command makes download requests. No default/main URLs.
    for model in cfg["models"]:
        target = inside(experiment, "checkpoints/" + model["filename"])
        target.parent.mkdir(parents=True, exist_ok=True)
        url = f"https://huggingface.co/{model['repo']}/resolve/{model['revision']}/{model['filename']}"
        if target.exists():
            if hash_file(target) != model["sha256"]:
                raise ContractError("existing checkpoint differs; no overwrite: " + target.name)
        else:
            fd, temporary = tempfile.mkstemp(prefix=".download-", dir=target.parent)
            try:
                with os.fdopen(fd, "wb") as output, urllib.request.urlopen(url, timeout=120) as response:
                    while chunk := response.read(1024 * 1024):
                        output.write(chunk)
                    output.flush(); os.fsync(output.fileno())
                if hash_file(temporary) != model["sha256"]:
                    raise ContractError("downloaded checkpoint SHA-256 disagrees with plan")
                try:
                    os.link(temporary, target)
                except FileExistsError:
                    if hash_file(target) != model["sha256"]:
                        raise ContractError("concurrent checkpoint publication differs")
            finally:
                os.unlink(temporary)
        results.append({"path": "checkpoints/" + model["filename"], "sha256": model["sha256"],
                        "download_url": url, "size_bytes": target.stat().st_size})
    value = signed({"status": "PREPARED", "checkpoints": results, "holdout_value_pages_read": 0})
    atomic_json(inside(experiment, "environment/checkpoint_receipt.json"), value, immutable=True)
    return value


def runtime_identity(experiment, device):
    require_local_environment(experiment)
    if device not in {"cpu", "mps", "cuda"}:
        raise ContractError("explicit CPU/MPS/CUDA device required")
    receipt = verify_record(read_json(inside(experiment, "environment/installation.json")))
    if packages() != receipt["packages"]:
        raise ContractError("installed dependencies changed after preparation")
    for path, key in [("environment/requirements-t02.txt", "requirements_input_sha256"),
                      ("environment/requirements-resolved.txt", "requirements_resolved_sha256"),
                      ("environment/pip-install-report.json", "pip_install_report_sha256")]:
        if hash_file(inside(experiment, path)) != receipt[key]:
            raise ContractError("environment identity artifact changed")
    cfg = checkpoint_config(experiment)
    checkpoint_hashes = {}
    for model in cfg["models"]:
        if packages().get(model["package"]) != model["version"]:
            raise ContractError("neural package version differs")
        rel = "checkpoints/" + model["filename"]
        actual = hash_file(inside(experiment, rel))
        if actual != model["sha256"]:
            raise ContractError("checkpoint bytes differ")
        checkpoint_hashes[rel] = actual
    os.environ.update(cache_environment(experiment))
    import torch
    if device == "mps" and not torch.backends.mps.is_available():
        raise ContractError("MPS unavailable; no silent CPU fallback")
    if device == "cuda" and not torch.cuda.is_available():
        raise ContractError("CUDA unavailable; no silent CPU fallback")
    return {"python": platform.python_version(), "system": platform.system(), "machine": platform.machine(),
            "packages": packages(), "installation_record_sha256": receipt["record_sha256"],
            "device": device, "precision": cfg["precision"], "threads": cfg["threads"],
            "torch": torch.__version__, "cuda_version": torch.version.cuda,
            "device_name": torch.cuda.get_device_name() if device == "cuda" else platform.machine(),
            "checkpoints": checkpoint_hashes, "checkpoint_config_sha256": hash_file(inside(experiment, "config/checkpoints.json"))}


def backend(experiment, name, device, *, checked=False):
    """Released API only; capacity guarded BEFORE fit, no reduction fallback."""
    if not checked:
        runtime_identity(experiment, device)
    cfg = checkpoint_config(experiment)
    model = next(m for m in cfg["models"] if m["name"] == name)
    path = inside(experiment, "checkpoints/" + model["filename"])
    import torch
    torch.set_num_threads(cfg["threads"]); torch.manual_seed(cfg["seed"])
    if name == "tabicl":
        from tabicl import TabICLRegressor
        return TabICLRegressor(n_estimators=cfg["ensemble_views"], norm_methods=["none", "power"],
                              feat_shuffle_method="latin", outlier_threshold=4., batch_size=1,
                              kv_cache="repr", model_path=str(path), allow_auto_download=False,
                              checkpoint_version=model["filename"], device=device, use_amp=False,
                              use_fa3=False, offload_mode="cpu", random_state=cfg["seed"],
                              n_jobs=cfg["threads"], verbose=False)
    from tabdpt import TabDPTRegressor
    result = TabDPTRegressor(normalizer="standard", missing_indicators=False, clip_sigma=8.,
                             feature_reduction="pca", context_reduction="subsample", device=device,
                             use_flash=False, compile=False, model_weight_path=str(path), verbose=False)
    if result.max_features < 71:
        raise ContractError("checkpoint feature capacity <71; PCA/subsampling is forbidden")
    return result


def raw_predict(model, name, X):
    import numpy as np
    if X.shape[1] != 71 or not np.isfinite(X).all():
        raise ContractError("native model requires exactly 71 finite columns")
    if name == "tabicl":
        output = np.asarray(model.predict(X, output_type="raw_quantiles"), dtype=np.float64)
        if output.shape != (len(X), 999) or not np.isfinite(output).all():
            raise ContractError("unexpected TabICL raw quantile output")
        return {"quantiles": output}
    if model.max_features < 71 or getattr(model, "projection", None) is not None:
        raise ContractError("TabDPT feature reduction was engaged")
    full = model.predict(X, n_ensembles=8, context_size=None, batch_size=1, seed=42, output_type="full")
    values = {k: np.asarray(v.detach().cpu().numpy() if hasattr(v, "detach") else v, dtype=np.float64)
              for k, v in full.items() if k in {"borders", "logits"}}
    edges, logits = values["borders"], values["logits"]
    if (edges.ndim != 1 or logits.shape != (len(X), len(edges)-1) or not np.isfinite(edges).all()
            or not np.isfinite(logits).all() or not (np.diff(edges) > 0).all()):
        raise ContractError("unexpected TabDPT native histogram output")
    return values


def probe(experiment, device):
    """Owner-run fixed synthetic fixture, not weather fitting or tuning.

    Same 71 inputs/eight views/full supplied context and precision as replay.
    No study labels or forecast scores are consulted. This is a capability smoke
    check, NOT a claim that larger later contexts will be fast or fit memory.
    """
    identity = runtime_identity(experiment, device)
    accepted = inside(experiment, f"environment/probe-{device}.json")
    if accepted.exists():
        old = verify_record(read_json(accepted))
        if old["runtime_identity"] != identity or old["implementation_identity"] != probe_code_identity(experiment):
            raise ContractError("existing device probe runtime/implementation differs")
        return old
    with no_network():
        return _probe(experiment, device, identity)


def _probe(experiment, device, identity):
    import numpy as np
    import torch
    rng = np.random.default_rng(42)
    X = rng.normal(size=(180, 71)); y = rng.normal(size=180); query = rng.normal(size=(2, 71))
    results = {}
    def sync():
        if device == "mps": torch.mps.synchronize()
        elif device == "cuda": torch.cuda.synchronize()
    for name in ["tabicl", "tabdpt"]:
        start = time.monotonic()
        model = backend(experiment, name, device, checked=True)
        model.fit(X, y)
        if name == "tabdpt" and (model.n_instances != 180 or model.n_features != 71 or model.projection is not None):
            raise ContractError("synthetic context or feature set was reduced")
        sync(); fit_seconds = time.monotonic() - start
        start = time.monotonic(); full = raw_predict(model, name, query); sync()
        prediction_seconds = time.monotonic() - start
        reversed_full = raw_predict(model, name, query[::-1])
        singleton = [raw_predict(model, name, query[i:i+1]) for i in range(2)]
        for key, value in full.items():
            if key == "borders":
                candidates = [reversed_full[key], *(a[key] for a in singleton)]
                if any(not np.allclose(value, a, atol=1e-5, rtol=1e-5) for a in candidates):
                    raise ContractError("histogram borders depend on query batching")
            elif (not np.allclose(value, reversed_full[key][::-1], atol=1e-5, rtol=1e-5)
                  or not np.allclose(value, np.concatenate([a[key] for a in singleton]), atol=1e-5, rtol=1e-5)):
                raise ContractError("native output depends on query order/batch")
        results[name] = {"context_rows": 180, "features": 71, "views": 8,
                         "capacity_proof": "FULL_NATIVE_INFERENCE_ACCEPTED_71_COLUMNS",
                         "declared_max_features": getattr(model, "max_features", None),
                         "fit_setup_seconds": fit_seconds, "two_query_predict_seconds": prediction_seconds,
                         "query_order_and_batch_invariant": True,
                         "output_shapes": {k: list(v.shape) for k, v in full.items()}}
        del model
    result = signed({"status": "PASS", "runtime_identity": identity, "implementation_identity": probe_code_identity(experiment), "fixture": "SYNTHETIC_SEED42_180_CONTEXT_2_QUERIES_71_FEATURES",
                     "probe_results": results, "full_replay_capacity_proven": False,
                     "study_model_fits_performed": 0, "synthetic_context_fits_performed": 2,
                     "holdout_value_pages_read": 0, "network_requests_made": 0})
    path = inside(experiment, f"environment/probe-{device}.json")
    atomic_json(path, result, immutable=True)
    return result
