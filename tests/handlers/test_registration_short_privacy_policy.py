"""На шаге «политика после правил» бот показывает краткую версию политики.

Краткая версия — инфо-страница со slug `privacy-policy-short`. Полная системная
политика остаётся в кабинете и меню «Инфо», а сюда попадает только запасным
вариантом: когда краткой страницы нет, она выключена или её текст пуст.
Переключатель системной политики в админке по-прежнему выключает весь шаг.
"""

import re
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.handlers import start
from app.states import RegistrationStates
from app.utils.telegram_html import TELEGRAM_ALLOWED_TAGS


SYSTEM_POLICY_HTML = '<p>Полная политика</p>'
SYSTEM_POLICY_TEXT = 'Полная политика'

_TAG_RE = re.compile(r'<\s*/?\s*([a-zA-Z][\w-]*)')


def _disallowed_tags(text: str) -> set[str]:
    return {match.group(1).lower() for match in _TAG_RE.finditer(text)} - set(TELEGRAM_ALLOWED_TAGS)


class _RegistrationCallback:
    def __init__(self):
        self.sent: list[str] = []
        self.from_user = SimpleNamespace(id=1)
        self.message = SimpleNamespace(edit_text=self._send, answer=self._send)

    async def _send(self, text, **_kwargs):
        self.sent.append(text)
        return SimpleNamespace()


def _page(content: dict, *, is_active: bool = True):
    return SimpleNamespace(slug=start.PRIVACY_POLICY_SHORT_SLUG, is_active=is_active, content=content)


@pytest.fixture
def system_policy(monkeypatch):
    policy = SimpleNamespace(is_enabled=True, content=SYSTEM_POLICY_HTML)
    monkeypatch.setattr(start.PrivacyPolicyService, 'get_policy', AsyncMock(return_value=policy))
    return policy


def _mock_short_page(monkeypatch, page) -> AsyncMock:
    getter = AsyncMock(return_value=page)
    monkeypatch.setattr(start, 'get_info_page_by_slug', getter)
    return getter


@pytest.mark.asyncio
async def test_active_short_page_is_shown_instead_of_system_policy(monkeypatch, system_policy):
    getter = _mock_short_page(
        monkeypatch,
        _page({'ru': '<h1>Кратко о данных</h1><p>Храним только <strong>необходимое</strong>.</p>'}),
    )
    callback = _RegistrationCallback()
    state = AsyncMock()
    db = AsyncMock()

    shown = await start._show_privacy_policy_after_rules(callback, state, db, 'ru')

    assert shown is True
    assert callback.sent, 'политика не отправлена'
    text = ''.join(callback.sent)
    assert not _disallowed_tags(text), callback.sent
    assert 'Кратко о данных' in text
    assert SYSTEM_POLICY_TEXT not in text
    getter.assert_awaited_once_with(db, 'privacy-policy-short')
    state.set_state.assert_awaited_once_with(RegistrationStates.waiting_for_privacy_policy_accept)


@pytest.mark.asyncio
async def test_missing_short_page_falls_back_to_system_policy(monkeypatch, system_policy):
    _mock_short_page(monkeypatch, None)
    callback = _RegistrationCallback()

    shown = await start._show_privacy_policy_after_rules(callback, AsyncMock(), AsyncMock(), 'ru')

    assert shown is True
    assert callback.sent == [SYSTEM_POLICY_TEXT]


@pytest.mark.asyncio
async def test_inactive_short_page_falls_back_to_system_policy(monkeypatch, system_policy):
    _mock_short_page(monkeypatch, _page({'ru': '<p>Кратко</p>'}, is_active=False))
    callback = _RegistrationCallback()

    shown = await start._show_privacy_policy_after_rules(callback, AsyncMock(), AsyncMock(), 'ru')

    assert shown is True
    assert callback.sent == [SYSTEM_POLICY_TEXT]


@pytest.mark.asyncio
@pytest.mark.parametrize('content', ['', '   ', '<p> </p><h1></h1>'])
async def test_empty_short_page_falls_back_to_system_policy(monkeypatch, system_policy, content):
    _mock_short_page(monkeypatch, _page({'ru': content}))
    callback = _RegistrationCallback()

    shown = await start._show_privacy_policy_after_rules(callback, AsyncMock(), AsyncMock(), 'ru')

    assert shown is True
    assert callback.sent == [SYSTEM_POLICY_TEXT]


@pytest.mark.asyncio
async def test_short_page_without_user_language_uses_russian(monkeypatch, system_policy):
    _mock_short_page(monkeypatch, _page({'ru': '<p>Кратко</p>', 'en': ''}))
    callback = _RegistrationCallback()

    shown = await start._show_privacy_policy_after_rules(callback, AsyncMock(), AsyncMock(), 'en')

    assert shown is True
    assert callback.sent == ['Кратко']


@pytest.mark.asyncio
async def test_disabled_system_policy_skips_step_even_with_short_page(monkeypatch):
    policy = SimpleNamespace(is_enabled=False, content=SYSTEM_POLICY_HTML)
    monkeypatch.setattr(start.PrivacyPolicyService, 'get_policy', AsyncMock(return_value=policy))
    _mock_short_page(monkeypatch, _page({'ru': '<p>Кратко</p>'}))
    callback = _RegistrationCallback()
    state = AsyncMock()

    shown = await start._show_privacy_policy_after_rules(callback, state, AsyncMock(), 'ru')

    assert shown is False
    assert callback.sent == []
    state.set_state.assert_not_awaited()
