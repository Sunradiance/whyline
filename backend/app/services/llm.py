import json
import re
from typing import Type, TypeVar

from openai import OpenAI
from pydantic import BaseModel, Field, ValidationError

from ..config import Config

T = TypeVar('T', bound=BaseModel)


class Alternative(BaseModel):
    option: str = ''
    whyRejected: str = ''


class DecisionExtract(BaseModel):
    title: str
    summary: str = ''
    reasoning: str = ''
    alternativesConsidered: list[Alternative] = Field(default_factory=list)
    decidedBy: str = ''
    decidedAt: str | None = None
    topics: list[str] = Field(default_factory=list)
    confidence: int = 3


class AskTrailStep(BaseModel):
    step: str
    detail: str


class AskResult(BaseModel):
    answer: str
    confidence: str = 'medium'
    decisionIds: list[str] = Field(default_factory=list)
    trail: list[AskTrailStep] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)


def _client():
    if not Config.LLM_API_KEY:
        raise RuntimeError('LLM_API_KEY not configured')
    return OpenAI(api_key=Config.LLM_API_KEY, base_url=Config.LLM_BASE_URL)


def _strip_think(text: str) -> str:
    text = re.sub(r'<think>[\s\S]*?</think>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'<think>[\s\S]*$', '', text, flags=re.IGNORECASE)
    return text.strip()


def _extract_json_text(text: str) -> str:
    text = _strip_think(text)
    m = re.search(r'```(?:json)?\s*([\s\S]*?)```', text)
    if m:
        return m.group(1).strip()
    m = re.search(r'\{[\s\S]*\}', text)
    if m:
        return m.group(0)
    m = re.search(r'\[[\s\S]*\]', text)
    return m.group(0) if m else text


def _chat_json(system: str, user: str, model_cls: Type[T], temp: float = 0.3) -> T:
    last_err = None
    for attempt in range(2):
        try:
            kwargs = dict(
                model=Config.LLM_MODEL_NAME,
                temperature=temp,
                messages=[
                    {'role': 'system', 'content': system + ' Respond with valid JSON only.'},
                    {'role': 'user', 'content': user},
                ],
            )
            try:
                resp = _client().chat.completions.create(**kwargs, response_format={'type': 'json_object'})
            except Exception:
                resp = _client().chat.completions.create(**kwargs)
            raw = _extract_json_text(resp.choices[0].message.content or '{}')
            data = json.loads(raw)
            return model_cls.model_validate(data)
        except Exception as e:
            last_err = e
            system += ' Previous response invalid. Return strict JSON matching schema.'
    raise RuntimeError(f'LLM JSON failed: {last_err}')


def extract_decision_from_thread(messages: list[dict], source_hint: str = 'slack') -> DecisionExtract:
    system = (
        'Extract ONE company decision from this conversation thread. JSON keys: '
        'title, summary, reasoning, alternativesConsidered (array of {option, whyRejected}), '
        'decidedBy, decidedAt (YYYY-MM-DD or null), topics (array), confidence (1-5).'
    )
    return _chat_json(system, json.dumps({'source': source_hint, 'messages': messages}, ensure_ascii=False), DecisionExtract)


def synthesize_decision(fragments: list) -> DecisionExtract:
    system = 'Stitch fragments into one decision. Same JSON schema as extract.'
    return _chat_json(system, json.dumps(fragments, ensure_ascii=False), DecisionExtract)


def ask_why(question: str, decisions: list[dict]) -> AskResult:
    corpus = []
    for d in decisions:
        corpus.append({
            'id': d['id'],
            'title': d.get('title'),
            'summary': d.get('summary'),
            'reasoning': d.get('reasoning'),
            'decidedBy': d.get('decidedBy'),
            'decidedAt': d.get('decidedAt'),
            'status': d.get('status'),
            'sources': [{'url': s.get('url'), 'type': s.get('sourceType'), 'ref': s.get('externalRef')}
                        for s in d.get('sources', [])],
        })
    system = (
        'Company memory engine. Answer ONLY from provided decisions. '
        'JSON: answer (markdown), confidence (high|medium|low|none), '
        'decisionIds (array of id strings FROM corpus only), trail (array of {step, detail}), gaps (array).'
    )
    payload = json.dumps({'question': question, 'decisions': corpus}, ensure_ascii=False)
    return _chat_json(system, payload, AskResult, temp=0.2)


def enhance_brief(brief: str, context: dict) -> str:
    return _strip_think(_client().chat.completions.create(
        model=Config.LLM_MODEL_NAME, temperature=0.3,
        messages=[
            {'role': 'system', 'content': 'Polish institutional memory brief. Markdown. Cite decision IDs. No marketing taglines.'},
            {'role': 'user', 'content': f'Brief:\n{brief}\n\nContext:\n{json.dumps(context, ensure_ascii=False)}'},
        ],
    ).choices[0].message.content or brief)


def ingest_jira_payload(payload: dict) -> DecisionExtract:
    system = 'Extract decision from Jira issue/comments. Same decision JSON schema. Include jira key context in title.'
    return _chat_json(system, json.dumps(payload, ensure_ascii=False), DecisionExtract)


def extract_decision_from_transcript(segments: list[dict], meta: dict | None = None) -> DecisionExtract:
    system = (
        'Extract ONE company decision from this meeting transcript. '
        'Use speaker names and timestamps for decidedBy/decidedAt when possible. '
        'Same JSON schema: title, summary, reasoning, alternativesConsidered, decidedBy, decidedAt, topics, confidence.'
    )
    return _chat_json(system, json.dumps({'meta': meta or {}, 'segments': segments}, ensure_ascii=False), DecisionExtract)


def extract_decision_from_doc(title: str, text: str, source_type: str = 'doc') -> DecisionExtract:
    system = (
        f'Extract ONE company decision from this {source_type} document (RFC/PRD/decision doc). '
        'Same JSON schema. Use document title for context.'
    )
    return _chat_json(system, json.dumps({'title': title, 'text': text, 'source': source_type}, ensure_ascii=False), DecisionExtract)


def extract_decision_from_github(payload: dict) -> DecisionExtract:
    system = (
        'Extract ONE company decision from this GitHub issue/PR discussion or ADR. '
        'Same JSON schema. Reference repo/issue/PR in title when relevant.'
    )
    return _chat_json(system, json.dumps(payload, ensure_ascii=False), DecisionExtract)


def extract_decision_from_linear(payload: dict) -> DecisionExtract:
    system = 'Extract ONE company decision from this Linear issue/comment thread. Same JSON schema.'
    return _chat_json(system, json.dumps(payload, ensure_ascii=False), DecisionExtract)


def extract_decision_from_salesforce(payload: dict) -> DecisionExtract:
    system = 'Extract ONE scoped business decision from this Salesforce note/opportunity/case. Same JSON schema.'
    return _chat_json(system, json.dumps(payload, ensure_ascii=False), DecisionExtract)