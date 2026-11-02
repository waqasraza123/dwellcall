import pytest

from dwellcall.consultant.catalog import PropertyRequirements
from dwellcall.consultant.state import ConsultationSession, RequirementExtraction
from dwellcall.crm.schemas import ConfirmedContact, ConsultationSnapshot
from dwellcall.settings import ApiSettings
from dwellcall.telephony.retell.schemas import Utterance


def requirements(**changes: object) -> PropertyRequirements:
    return PropertyRequirements.model_validate({
        "scenario": "renting", "max_budget": 2300, "bedrooms": 1,
        "pets": True, **changes,
    })


def review(session: ConsultationSession, settings: ApiSettings) -> str:
    update = session.propose(
        RequirementExtraction(requirements=requirements(), intent="review"),
        [Utterance(role="user", content="Please recap my requirements")], settings,
    )
    session.commit(update)
    assert session.pending_readback is not None
    return session.pending_readback


def test_confirmation_requires_current_readback_and_separate_caller_turn(settings: ApiSettings) -> None:
    session = ConsultationSession()
    readback = review(session, settings)
    update = session.propose(RequirementExtraction(requirements=requirements()), [
        Utterance(role="agent", content=readback), Utterance(role="user", content="Yes, correct"),
    ], settings)
    session.commit(update)
    assert session.confirmed_version == 1
    fields = session.confirmed_fields(settings)
    assert "crm_permission" not in fields and "storage_permission" not in fields
    assert "contact" not in fields
    snapshot = ConsultationSnapshot.model_validate({
        **fields, "contact": ConfirmedContact(email="visitor@example.com").model_dump(),
    })
    assert snapshot.scenario == "renting"
    assert "2300" in snapshot.summary


@pytest.mark.parametrize("reply", ["yes, but make it two bedrooms", "no", "maybe", "yes and send this to my CRM"])
def test_qualified_or_unclear_yes_does_not_confirm(settings: ApiSettings, reply: str) -> None:
    session = ConsultationSession()
    readback = review(session, settings)
    session.commit(session.propose(RequirementExtraction(requirements=requirements()), [
        Utterance(role="agent", content=readback), Utterance(role="user", content=reply),
    ], settings))
    assert session.confirmed_version is None
    with pytest.raises(ValueError):
        session.confirmed_fields(settings)


def test_partial_spoken_or_missing_readback_cannot_confirm(settings: ApiSettings) -> None:
    session = ConsultationSession()
    readback = review(session, settings)
    session.commit(session.propose(RequirementExtraction(requirements=requirements()), [
        Utterance(role="agent", content=readback[:40]), Utterance(role="user", content="yes"),
    ], settings))
    assert session.confirmed_version is None


def test_correction_invalidates_old_revision_and_confirmation(settings: ApiSettings) -> None:
    session = ConsultationSession()
    readback = review(session, settings)
    session.commit(session.propose(RequirementExtraction(requirements=requirements()), [
        Utterance(role="agent", content=readback), Utterance(role="user", content="yes"),
    ], settings))
    session.commit(session.propose(
        RequirementExtraction(requirements=requirements(max_budget=2000, pets=None)),
        [Utterance(role="user", content="Actually, under 2000 and ignore the pets preference")], settings,
    ))
    assert session.version == 2
    assert session.confirmed_version is None and session.pending_readback is None
    assert session.requirements.pets is None
    with pytest.raises(ValueError):
        session.confirmed_fields(settings)


def test_separate_calls_do_not_share_state_and_closing_does_not_imply_consent(settings: ApiSettings) -> None:
    first, second = ConsultationSession(), ConsultationSession()
    review(first, settings)
    assert second.version == 0 and second.pending_readback is None
    update = first.propose(RequirementExtraction(requirements=requirements()), [
        Utterance(role="user", content="Goodbye"),
    ], settings)
    assert update.end_call is True and update.confirmed_version is None
    assert "No showing" in update.reply
    assert second.end_call is False


def test_human_request_is_an_unavailable_decision_not_a_transfer(settings: ApiSettings) -> None:
    session = ConsultationSession()
    update = session.propose(RequirementExtraction(
        requirements=requirements(), intent="handoff",
    ), [Utterance(role="user", content="Can I speak to a human?")], settings)
    assert "not enabled" in update.reply and not update.end_call


def test_yes_after_an_old_revision_readback_cannot_confirm_new_requirements(settings: ApiSettings) -> None:
    session = ConsultationSession()
    previous = review(session, settings)
    changed = RequirementExtraction(requirements=requirements(max_budget=2600), intent="review")
    session.commit(session.propose(changed, [Utterance(role="user", content="Change the budget and recap")], settings))
    assert session.version == 2 and session.pending_readback != previous
    session.commit(session.propose(RequirementExtraction(requirements=changed.requirements), [
        Utterance(role="agent", content=previous), Utterance(role="user", content="yes"),
    ], settings))
    assert session.confirmed_version is None


def test_unicode_location_is_part_of_the_required_spoken_readback(settings: ApiSettings) -> None:
    configured = settings.model_copy(update={"supported_location": "لاہور"})
    session = ConsultationSession()
    readback = review(session, configured)
    session.commit(session.propose(RequirementExtraction(requirements=requirements()), [
        Utterance(role="agent", content=readback.replace("لاہور", "")),
        Utterance(role="user", content="yes"),
    ], configured))
    assert session.confirmed_version is None
