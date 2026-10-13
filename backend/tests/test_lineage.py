from datasentinel.lineage.graph import (
    Graph,
    downstream,
    find_cycles,
    layered_layout,
    upstream,
    would_create_cycle,
)
from tests.helpers import ORDERS_CSV, import_ok


def make_graph(edges, extra_nodes=()):
    graph = Graph()
    for node in sorted({n for e in edges for n in e} | set(extra_nodes)):
        graph.add_node(node, name=node, kind="dataset")
    for source, target in edges:
        graph.add_edge(source, target)
    return graph


DIAMOND = [("src", "a"), ("src", "b"), ("a", "c"), ("b", "c"), ("c", "report")]


def test_downstream_upstream_with_shortest_paths():
    graph = make_graph(DIAMOND, extra_nodes=["island"])
    down = downstream(graph, "src")
    assert {n: i["distance"] for n, i in down.items()} == {"a": 1, "b": 1, "c": 2, "report": 3}
    assert down["report"]["path"] == ["src", "a", "c", "report"]
    up = upstream(graph, "report")
    assert set(up) == {"c", "a", "b", "src"}
    assert up["src"]["path"] == ["src", "a", "c", "report"]
    assert downstream(graph, "island") == {} and upstream(graph, "island") == {}


def test_cycle_prevention_returns_the_cycle():
    graph = make_graph(DIAMOND)
    assert would_create_cycle(graph, "report", "src") == ["src", "a", "c", "report", "src"]
    assert would_create_cycle(graph, "a", "a") == ["a", "a"]
    assert would_create_cycle(graph, "src", "report") is None


def test_traversals_terminate_on_cyclic_graphs():
    graph = make_graph([("a", "b"), ("b", "c"), ("c", "a"), ("c", "d"), ("e", "e")])
    assert set(downstream(graph, "a")) == {"b", "c", "d"}
    cycles = find_cycles(graph)
    assert ["a", "b", "c"] in cycles and ["e"] in cycles
    positions = layered_layout(graph)
    assert set(positions) == set(graph.nodes)


def test_layout_is_layered_by_longest_path():
    positions = layered_layout(make_graph([*DIAMOND, ("src", "report")]))
    assert positions["src"]["x"] == 0
    assert positions["c"]["x"] == 2 * 280
    assert positions["report"]["x"] == 3 * 280


def test_large_chain_has_no_recursion_problems():
    edges = [(f"n{i:05d}", f"n{i + 1:05d}") for i in range(5000)]
    graph = make_graph(edges)
    assert len(downstream(graph, "n00000")) == 5000
    assert find_cycles(graph) == []


# ---------------------------------------------------------------- API


def _setup(client):
    ds = import_ok(client, ORDERS_CSV, dataset_name="orders")["dataset"]
    job = client.post("/api/v1/lineage/assets", json={"name": "revenue job", "kind": "transformation"}).json()
    report = client.post(
        "/api/v1/lineage/assets", json={"name": "exec report", "kind": "report", "owner": "finance"}
    ).json()
    assert (
        client.post("/api/v1/lineage/edges", json={"source_id": ds["asset_id"], "target_id": job["id"]}).status_code
        == 201
    )
    client.post("/api/v1/lineage/edges", json={"source_id": job["id"], "target_id": report["id"]})
    return ds, job, report


def test_lineage_graph_endpoint(client):
    _ds, _job, _report = _setup(client)
    graph = client.get("/api/v1/lineage").json()
    assert {n["name"] for n in graph["nodes"]} == {"orders", "revenue job", "exec report"}
    assert len(graph["edges"]) == 2 and graph["cycles"] == []
    orders = next(n for n in graph["nodes"] if n["name"] == "orders")
    assert orders["health"]["state"] == "unvalidated"
    assert next(n for n in graph["nodes"] if n["kind"] == "report")["health"]["state"] == "no_checks"


def test_cycle_edge_rejected_with_explanation(client):
    ds, job, report = _setup(client)
    response = client.post("/api/v1/lineage/edges", json={"source_id": report["id"], "target_id": ds["asset_id"]})
    assert response.status_code == 409
    body = response.json()["error"]
    assert "acyclic" in body["message"] and "orders → revenue job → exec report → orders" in body["message"]
    duplicate = client.post("/api/v1/lineage/edges", json={"source_id": job["id"], "target_id": report["id"]})
    assert duplicate.status_code == 409


def test_asset_details_upstream_downstream_and_versions(client):
    ds, _job, report = _setup(client)
    details = client.get(f"/api/v1/lineage/{ds['asset_id']}").json()
    assert [d["name"] for d in details["downstream"]] == ["revenue job", "exec report"]
    assert details["downstream"][1]["path"] == ["orders", "revenue job", "exec report"]
    assert details["versions"][0]["version_number"] == 1
    up = client.get(f"/api/v1/lineage/{report['id']}").json()["upstream"]
    assert [u["name"] for u in up] == ["revenue job", "orders"]


def test_asset_crud_rules(client):
    ds, job, _ = _setup(client)
    assert client.post("/api/v1/lineage/assets", json={"name": "x", "kind": "dataset"}).status_code == 422
    assert client.post("/api/v1/lineage/assets", json={"name": "revenue job", "kind": "model"}).status_code == 409
    assert client.delete(f"/api/v1/lineage/assets/{ds['asset_id']}").status_code == 409
    renamed = client.patch(f"/api/v1/lineage/assets/{job['id']}", json={"name": "revenue job v2"}).json()
    assert renamed["name"] == "revenue job v2"
    assert client.delete(f"/api/v1/lineage/assets/{job['id']}").json()["deleted"] is True
    assert len(client.get("/api/v1/lineage").json()["edges"]) == 0  # edges cascade
    assert client.get("/api/v1/lineage/asset_nope").status_code == 404
