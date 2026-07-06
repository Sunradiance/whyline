def test_upsert_and_list(store):
    d = store.upsert_decision({
        'title': 'No annual billing in Germany',
        'summary': 'Monthly only in DACH',
        'reasoning': 'VAT compliance gap',
        'decidedBy': 'CFO',
        'sourceType': 'meeting',
    }, sources=[{'sourceType': 'meeting', 'url': 'https://example.com', 'externalRef': 'M-1'}])
    assert d['title'] == 'No annual billing in Germany'
    assert d['sources'][0]['url'] == 'https://example.com'
    assert len(store.list_decisions()) == 1


def test_content_hash_dedup(store):
    payload = {'title': 'Same', 'summary': 'x', 'reasoning': 'y'}
    a = store.upsert_decision(payload)
    b = store.upsert_decision(payload)
    assert a['id'] == b['id']


def test_source_key_dedup(store):
    payload = {'title': 'Slack thread', 'summary': 'a', 'reasoning': 'b'}
    a = store.upsert_decision(payload, source_key='slack:C1:123.456')
    b = store.upsert_decision({'title': 'Other', 'summary': 'c', 'reasoning': 'd'}, source_key='slack:C1:123.456')
    assert a['id'] == b['id']


def test_supersede(store):
    old = store.upsert_decision({'title': 'Old policy', 'summary': '', 'reasoning': 'was'})
    new = store.upsert_decision({'title': 'New policy', 'summary': '', 'reasoning': 'now'})
    store.supersede(old['id'], new['id'])
    updated = store.get_decision(old['id'])
    assert updated['status'] == 'superseded'
    assert updated['supersededBy'] == new['id']


def test_search(store):
    store.upsert_decision({'title': 'Acme CDN rejected', 'summary': '', 'reasoning': 'EU routing'})
    store.upsert_decision({'title': 'Teams killed', 'summary': '', 'reasoning': 'low DAU'})
    hits = store.list_decisions(search='Acme')
    assert len(hits) == 1
    assert 'Acme' in hits[0]['title']