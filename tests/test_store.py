def _ws(store):
    return store.get_default_workspace_id()


def test_upsert_and_list(store):
    ws = _ws(store)
    d = store.upsert_decision({
        'title': 'No annual billing in Germany',
        'summary': 'Monthly only in DACH',
        'reasoning': 'VAT compliance gap',
        'decidedBy': 'CFO',
        'sourceType': 'meeting',
    }, sources=[{'sourceType': 'meeting', 'url': 'https://example.com', 'externalRef': 'M-1'}],
       workspace_id=ws)
    assert d['title'] == 'No annual billing in Germany'
    assert d['sources'][0]['url'] == 'https://example.com'
    assert len(store.list_decisions(workspace_id=ws)) == 1


def test_content_hash_dedup(store):
    ws = _ws(store)
    payload = {'title': 'Same', 'summary': 'x', 'reasoning': 'y'}
    a = store.upsert_decision(payload, workspace_id=ws)
    b = store.upsert_decision(payload, workspace_id=ws)
    assert a['id'] == b['id']


def test_source_key_dedup(store):
    ws = _ws(store)
    payload = {'title': 'Slack thread', 'summary': 'a', 'reasoning': 'b'}
    a = store.upsert_decision(payload, source_key='slack:C1:123.456', workspace_id=ws)
    b = store.upsert_decision({'title': 'Other', 'summary': 'c', 'reasoning': 'd'}, source_key='slack:C1:123.456', workspace_id=ws)
    assert a['id'] == b['id']


def test_supersede(store):
    ws = _ws(store)
    old = store.upsert_decision({'title': 'Old policy', 'summary': '', 'reasoning': 'was'}, workspace_id=ws)
    new = store.upsert_decision({'title': 'New policy', 'summary': '', 'reasoning': 'now'}, workspace_id=ws)
    store.supersede(old['id'], new['id'], workspace_id=ws)
    updated = store.get_decision(old['id'], workspace_id=ws)
    assert updated['status'] == 'superseded'
    assert updated['supersededBy'] == new['id']


def test_search(store):
    ws = _ws(store)
    store.upsert_decision({'title': 'Acme CDN rejected', 'summary': '', 'reasoning': 'EU routing'}, workspace_id=ws)
    store.upsert_decision({'title': 'Teams killed', 'summary': '', 'reasoning': 'low DAU'}, workspace_id=ws)
    hits = store.list_decisions(workspace_id=ws, search='Acme')
    assert len(hits) == 1
    assert 'Acme' in hits[0]['title']