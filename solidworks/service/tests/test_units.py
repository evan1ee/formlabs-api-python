from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request

import attrs
import pytest

from formlabs_sw_service import transform as T
from formlabs_sw_service.db import MIGRATIONS, Database
from formlabs_sw_service.http_api import make_server
from formlabs_sw_service.keys import build_key, normalize_layer, setting_fingerprint, source_identity_key
from formlabs_sw_service.pathsafe import resolve_inside


def test_layer_normalisation():
    assert normalize_layer(0.1000004) == normalize_layer("0.1") == "0.100"
    assert normalize_layer("adaptive") == "ADAPTIVE"


def test_custom_setting_hash_in_key():
    a = build_key("F", "M", 0.1, setting_fingerprint("CUSTOM", {"x": 1}))
    b = build_key("F", "M", 0.1, setting_fingerprint("CUSTOM", {"x": 2}))
    assert a != b and build_key("F", "M", 0.1, "DEFAULT").endswith("|DEFAULT")


def test_identity_key_case_and_slash_insensitive():
    assert source_identity_key("C:\\A\\p.sldprt", "d", "1") == source_identity_key("c:/a/p.sldprt", "d", "1")


def test_path_traversal_blocked(tmp_path):
    (tmp_path / "ok").mkdir()
    assert resolve_inside(tmp_path, "ok")
    with pytest.raises(Exception):
        resolve_inside(tmp_path, "../x")


def test_transform_rotations():
    p = T.apply(T.rotation("z", 90), (1, 0, 0))
    assert p == pytest.approx((0, 1, 0), abs=1e-9)
    m = T.multiply(T.translation(5, 0, 0), T.rotation("x", 45))
    inv = T.invert_rigid(m)
    ident = T.multiply(m, inv)
    assert all(ident[i][j] == pytest.approx(1.0 if i == j else 0.0, abs=1e-9) for i in range(4) for j in range(4))
    T.validate_rigid(m)


@pytest.mark.parametrize("bad", ["scale", "mirror"])
def test_validate_rigid_rejects(bad):
    m = T.identity()
    m[0][0] = 2.0 if bad == "scale" else -1.0
    with pytest.raises(ValueError):
        T.validate_rigid(m)


def test_db_migrations_versioned(tmp_path):
    db = Database(tmp_path / "x.db")
    assert db.schema_version == len(MIGRATIONS)
    db.close()
    assert Database(tmp_path / "x.db").schema_version == len(MIGRATIONS)


def _call(url, token, body=None, method="GET"):
    req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body is not None else None)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, json.load(e)


def test_http_requires_token_and_runs_async_send(svc, make_req):
    server = make_server(svc, "s3cret")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        assert _call(base + "/health", None)[0] == 401
        assert _call(base + "/health", "wrong")[0] == 401
        assert _call(base + "/health", "s3cret")[0] == 200
        req = make_req()
        body = attrs.asdict(req)
        body["lock_mode"] = "LOCKED_ROTATION_FREE_TRANSLATION"
        code, res = _call(base + "/send", "s3cret", body, "POST")
        assert code == 200
        for _ in range(50):
            _, op = _call(base + "/operation/" + res["operation_id"], "s3cret")
            if op["state"] != "RUNNING":
                break
            time.sleep(0.05)
        assert op["state"] == "SUCCEEDED" and op["result"]["action"] == "imported"
        assert _call(base + "/build/submit", "s3cret", {"build_id": "x", "printer": "p", "job_name": "j"}, "POST")[0] == 200
    finally:
        server.shutdown()


def test_server_refuses_non_loopback(svc):
    with pytest.raises(ValueError):
        make_server(svc, "t", host="0.0.0.0")
