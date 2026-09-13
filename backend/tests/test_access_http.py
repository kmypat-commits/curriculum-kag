from types import SimpleNamespace

from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient

from app.database import get_db
from app.services.access import require_project_version_access, require_syllabus_entity_access
from app.services.auth import get_current_user


class _Query:
    def __init__(self, value):
        self.value = value

    def filter(self, *_args):
        return self

    def first(self):
        return self.value


class _DB:
    def __init__(self, version):
        self.version = version

    def query(self, _model):
        return _Query(self.version)


def test_http_owner_other_admin_access_contract():
    owner = SimpleNamespace(id=7, roles=[SimpleNamespace(name="analyst")])
    other = SimpleNamespace(id=8, roles=[SimpleNamespace(name="analyst")])
    admin = SimpleNamespace(id=9, roles=[SimpleNamespace(name="admin")])
    project = SimpleNamespace(created_by=7)
    version = SimpleNamespace(project=project)
    app = FastAPI()
    router = APIRouter(dependencies=[Depends(require_project_version_access)])

    @router.get("/planner/version/{project_version_id}/graph")
    def graph(project_version_id: int):
        return {"project_version_id": project_version_id}

    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: _DB(version)
    current = {"user": owner}
    app.dependency_overrides[get_current_user] = lambda: current["user"]
    client = TestClient(app)

    assert client.get("/planner/version/1/graph").status_code == 200
    current["user"] = other
    assert client.get("/planner/version/1/graph").status_code == 404
    current["user"] = admin
    assert client.get("/planner/version/1/graph").status_code == 200


def test_http_bridge_syllabus_is_owner_or_admin_only():
    owner = SimpleNamespace(id=7, roles=[SimpleNamespace(name="analyst")])
    other = SimpleNamespace(id=8, roles=[SimpleNamespace(name="analyst")])
    admin = SimpleNamespace(id=9, roles=[SimpleNamespace(name="admin")])
    project = SimpleNamespace(created_by=7)
    version = SimpleNamespace(project=project)
    bridge = SimpleNamespace(project_version_id=1)

    class BridgeDB(_DB):
        def query(self, model):
            if model.__name__ == "BridgeModule":
                return _Query(bridge)
            return _Query(version)

    app = FastAPI()
    router = APIRouter()

    @router.get("/planner/syllabus/{kind}/{entity_id}", dependencies=[Depends(require_syllabus_entity_access)])
    def syllabus(kind: str, entity_id: int):
        return {"kind": kind, "entity_id": entity_id}

    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: BridgeDB(version)
    current = {"user": owner}
    app.dependency_overrides[get_current_user] = lambda: current["user"]
    client = TestClient(app)

    assert client.get("/planner/syllabus/bridge/1").status_code == 200
    current["user"] = other
    assert client.get("/planner/syllabus/bridge/1").status_code == 404
    current["user"] = admin
    assert client.get("/planner/syllabus/bridge/1").status_code == 200


def test_real_app_build_status_enforces_owner_other_admin_matrix():
    """Exercise the registered planner route, not only a synthetic router."""
    from app.main import app

    owner = SimpleNamespace(id=7, roles=[SimpleNamespace(name="analyst")])
    other = SimpleNamespace(id=8, roles=[SimpleNamespace(name="analyst")])
    admin = SimpleNamespace(id=9, roles=[SimpleNamespace(name="admin")])
    version = SimpleNamespace(project=SimpleNamespace(created_by=7))
    current = {"user": owner}
    app.dependency_overrides[get_db] = lambda: _DB(version)
    app.dependency_overrides[get_current_user] = lambda: current["user"]
    try:
        client = TestClient(app)
        assert client.get("/planner/1/build-status").status_code == 200
        current["user"] = other
        assert client.get("/planner/1/build-status").status_code == 404
        current["user"] = admin
        assert client.get("/planner/1/build-status").status_code == 200
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user, None)


def test_real_app_global_model_endpoint_rejects_user_without_epvo_read():
    from app.main import app

    unprivileged = SimpleNamespace(id=10, roles=[SimpleNamespace(name="viewer")])
    app.dependency_overrides[get_current_user] = lambda: unprivileged
    try:
        client = TestClient(app)
        assert client.get("/epvo/lstm-gnn-manifest").status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_real_app_kag_global_state_requires_kag_read():
    from app.main import app

    viewer = SimpleNamespace(id=10, roles=[SimpleNamespace(name="viewer")])
    analyst = SimpleNamespace(id=11, roles=[SimpleNamespace(name="analyst")])
    current = {"user": viewer}
    app.dependency_overrides[get_current_user] = lambda: current["user"]
    try:
        client = TestClient(app)
        assert client.get("/kag/graph/stats").status_code == 403
        current["user"] = analyst
        # The permission boundary is tested independently of the live graph
        # storage; any post-auth response is acceptable here.
        assert client.get("/kag/graph/stats").status_code != 403
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_bridge_promotion_checks_project_version_ownership(monkeypatch):
    from app.main import app
    import app.api.kag as kag_api

    kag_admin = SimpleNamespace(resource="kag", action="admin")
    owner = SimpleNamespace(id=7, roles=[SimpleNamespace(name="analyst", permissions=[kag_admin])])
    other = SimpleNamespace(id=8, roles=[SimpleNamespace(name="analyst", permissions=[kag_admin])])
    project = SimpleNamespace(created_by=7)
    version = SimpleNamespace(project=project)
    bridge = SimpleNamespace(project_version_id=1)

    class BridgeDB(_DB):
        def query(self, model):
            if model.__name__ == "BridgeModule":
                return _Query(bridge)
            return _Query(version)

    app.dependency_overrides[get_db] = lambda: BridgeDB(version)
    current = {"user": owner}
    app.dependency_overrides[get_current_user] = lambda: current["user"]
    monkeypatch.setattr(kag_api, "promote_bridge_to_course", lambda **kwargs: {"course_id": 99})
    try:
        client = TestClient(app)
        # Owner reaches the promotion handler boundary; the mocked DB is not
        # intended to exercise the promotion implementation itself.
        assert client.post("/kag/bridge/1/promote").status_code != 404
        current["user"] = other
        assert client.post("/kag/bridge/1/promote").status_code == 404
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user, None)


def test_real_app_observability_summary_requires_planner_read():
    from app.main import app

    viewer = SimpleNamespace(id=10, roles=[SimpleNamespace(name="viewer")])
    analyst = SimpleNamespace(id=11, roles=[SimpleNamespace(name="analyst")])
    current = {"user": viewer}
    app.dependency_overrides[get_current_user] = lambda: current["user"]

    class EmptyQuery:
        def filter(self, *_args):
            return self

        def order_by(self, *_args):
            return self

        def limit(self, *_args):
            return self

        def all(self):
            return []

        def count(self):
            return 0

    app.dependency_overrides[get_db] = lambda: SimpleNamespace(query=lambda _model: EmptyQuery())
    try:
        client = TestClient(app)
        assert client.get("/planner/observability/summary").status_code == 403
        current["user"] = analyst
        # The permission boundary is the contract; the real DB may be absent in
        # this unit test, so a post-auth response is acceptable here.
        assert client.get("/planner/observability/summary").status_code != 403
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_db, None)
