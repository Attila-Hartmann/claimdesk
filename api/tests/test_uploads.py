from claimdesk import service, store


def test_visitor_uploads_are_private_and_counted(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "LOCAL", tmp_path)
    seeded = service.create_claim([("a.pdf", b"%PDF")], source="corpus")
    up = service.create_claim([("scan.JPG", b"img")])
    assert up.startswith("UP-") and len(up) > 16  # unguessable: the id is the only way in
    assert store.get_json(f"uploads/claims/{up}.json")["documents"][0]["file"] == f"uploads/files/{up}/1.jpg"
    assert [c["id"] for c in service.list_claims()] == [seeded]  # never in the public queue
    assert service.uploads_today() == 1
