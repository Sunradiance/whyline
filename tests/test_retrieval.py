from app.services.retrieval import score_decisions


def _dec(title, summary='', reasoning=''):
    return {'id': title, 'title': title, 'summary': summary, 'reasoning': reasoning,
            'decidedBy': '', 'alternativesConsidered': []}


def test_retrieval_ranks_relevant():
    corpus = [
        _dec('No annual billing in Germany', 'DACH monthly only', 'German VAT invoicing'),
        _dec('Rejected Acme CDN', 'stayed on edge', 'no EU-only path'),
        _dec('Killed Teams social', 'deprioritized feed', 'DAU 4%'),
    ]
    top = score_decisions('Why no annual billing in Germany?', corpus, top_k=2)
    assert top[0]['title'] == 'No annual billing in Germany'


def test_retrieval_empty_question_returns_subset():
    corpus = [_dec('A'), _dec('B'), _dec('C')]
    top = score_decisions('', corpus, top_k=2)
    assert len(top) == 2