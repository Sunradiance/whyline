def test_webhook_routes_to_workspace(store):
    from app.services.webhook_workspace import webhook_workspace_id
    a = store.create_workspace('Webhook WS')
    b = store.create_workspace('Other')
    store.upsert_decision({'title': 'in B', 'summary': 's', 'reasoning': 'r'}, workspace_id=b['id'])

    class FakeReq:
        headers = {'X-Whyline-Workspace': a['id']}
        @staticmethod
        def get_json(silent=True):
            return {}

    import app.services.webhook_workspace as ww
    old = ww.request
    ww.request = FakeReq()
    try:
        assert webhook_workspace_id() == a['id']
    finally:
        ww.request = old


def test_sensitive_hidden_from_member(store):
    ws = store.create_workspace('Secret WS')
    pub = store.upsert_decision({'title': 'public', 'summary': 's', 'reasoning': 'r'}, workspace_id=ws['id'])
    sec = store.upsert_decision(
        {'title': 'secret compensation band', 'summary': 'confidential', 'reasoning': 'exec only', 'sensitive': True},
        workspace_id=ws['id'],
    )
    member_view = store.list_decisions(workspace_id=ws['id'], actor_role='member')
    admin_view = store.list_decisions(workspace_id=ws['id'], actor_role='admin')
    assert pub['id'] in {d['id'] for d in member_view}
    assert sec['id'] not in {d['id'] for d in member_view}
    assert sec['id'] in {d['id'] for d in admin_view}
    assert store.get_decision(sec['id'], workspace_id=ws['id'], actor_role='member') is None
    assert store.get_decision(sec['id'], workspace_id=ws['id'], actor_role='admin') is not None


def test_create_workspace_and_invite(store):
    owner = store.create_user('owner@co.com', 'pass-12345')
    ws = store.create_workspace('Eng')
    store.add_member(ws['id'], owner['id'], 'owner')
    member = store.create_user('dev@co.com', 'pass-12345')
    store.add_member(ws['id'], member['id'], 'member')
    members = store.list_members(ws['id'])
    assert len(members) == 2
    assert store.can(member['id'], ws['id'], 'create')
    assert not store.can(member['id'], ws['id'], 'admin')


def test_public_read_toggle(store):
    ws = store.create_workspace('KB', public_read=False)
    updated = store.update_workspace(ws['id'], public_read=True)
    assert updated['public_read'] == 1
    assert store.workspace_is_public(ws['id'])