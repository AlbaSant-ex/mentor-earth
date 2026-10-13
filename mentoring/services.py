"""All mentoring state transitions live here; views never change these models directly."""

from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Count, F, Q
from django.utils import timezone

from .models import MentorProfile, MentoringRelationship, Notification

ACTIVE = MentoringRelationship.Status.ACTIVE
EXPIRED = MentoringRelationship.EndReason.EXPIRED


def relationship_duration():
    """How long a relationship lasts before it ends automatically (~4 months)."""
    return timedelta(days=getattr(settings, "MENTORING_RELATIONSHIP_DURATION_DAYS", 120))


def relationship_expires_at(rel):
    return rel.started_at + relationship_duration()


def active_cutoff(now=None):
    """Relationships started at or before this are past the 4-month limit."""
    return (now or timezone.now()) - relationship_duration()


def active_filter(now=None):
    """Q object matching only non-expired active relationships (no maintenance needed)."""
    return Q(status=ACTIVE, started_at__gt=active_cutoff(now))


class MentoringError(Exception):
    """A rule of the program prevents the requested action. The message is user-facing."""


def _notify(recipient, kind, message, relationship=None):
    # Phase 2: also send an email from here.
    return Notification.objects.create(
        recipient=recipient, kind=kind, message=message, relationship=relationship
    )


def _locked_profile(user):
    """Lock the mentor's row so capacity checks and writes can't interleave."""
    return MentorProfile.objects.select_for_update().filter(user=user).first()


# --- Queries -----------------------------------------------------------------


def mentor_profile(user):
    """The user's mentor profile if they are currently in the mentor pool, else None."""
    profile = MentorProfile.objects.filter(user=user).first()
    return profile if profile and profile.is_participating else None


def current_mentor_relationship(user):
    expire_user_relationships(user)
    return (
        MentoringRelationship.objects.filter(mentee=user, status=ACTIVE, started_at__gt=active_cutoff())
        .select_related("mentor", "mentor__mentor_profile")
        .first()
    )


def current_mentee_relationships(user):
    expire_user_relationships(user)
    return MentoringRelationship.objects.filter(
        mentor=user, status=ACTIVE, started_at__gt=active_cutoff()
    ).select_related("mentee")


def available_mentors(for_user, research=None, stage=None):
    """Mentors `for_user` could choose right now, in random order."""
    expire_user_relationships(for_user)
    cutoff = active_cutoff()
    qs = (
        MentorProfile.objects.filter(status=MentorProfile.Status.ACTIVE, user__is_active=True)
        .annotate(
            n_active=Count(
                "user__mentoring_as_mentor",
                filter=Q(
                    user__mentoring_as_mentor__status=ACTIVE,
                    user__mentoring_as_mentor__started_at__gt=cutoff,
                ),
            )
        )
        .filter(n_active__lt=F("capacity"))
        .exclude(user=for_user)
        .exclude(
            user__mentoring_as_mentor__mentee=for_user,
            user__mentoring_as_mentor__status=ACTIVE,
            user__mentoring_as_mentor__started_at__gt=cutoff,
        )
        .select_related("user")
    )
    if research:
        qs = qs.filter(user__research_topic__icontains=research)
    if stage:
        qs = qs.filter(user__career_stage=stage)
    return qs.order_by("?")


# --- Relationships -----------------------------------------------------------


@transaction.atomic
def choose_mentor(mentee, mentor):
    """Create an active relationship immediately; no approval step."""
    if mentee.pk == mentor.pk:
        raise MentoringError("You can't be your own mentor.")
    # Zero-maintenance expiry: free places held by 4-month-old matches first.
    expire_user_relationships(mentee)
    expire_user_relationships(mentor)
    profile = _locked_profile(mentor)
    if profile is None or profile.status != MentorProfile.Status.ACTIVE:
        raise MentoringError(f"{mentor.first_name} isn't taking new mentees right now.")
    if MentoringRelationship.objects.filter(
        mentee=mentee, status=ACTIVE, started_at__gt=active_cutoff()
    ).exists():
        raise MentoringError(
            "You already have a mentor. End that mentoring relationship first to choose another."
        )
    if profile.free_places < 1:
        raise MentoringError(f"{mentor.first_name}'s last place was just taken.")
    try:
        with transaction.atomic():
            rel = MentoringRelationship.objects.create(mentor=mentor, mentee=mentee)
    except IntegrityError:
        raise MentoringError("That match couldn't be made. Please try again.") from None

    _notify(
        mentor,
        Notification.Kind.MATCH_CREATED,
        f"{mentee} chose you as their mentor. You are now mentoring {mentee.first_name}.",
        rel,
    )
    _notify(
        mentee,
        Notification.Kind.MATCH_CREATED,
        f"{mentor} is now your mentor. Say hi whenever you're ready!",
        rel,
    )
    return rel


def _end(rel, by_user, reason="", kind=Notification.Kind.MATCH_ENDED):
    rel.status = MentoringRelationship.Status.ENDED
    rel.ended_at = timezone.now()
    rel.ended_by = by_user
    rel.end_reason = reason or ""
    rel.save(update_fields=["status", "ended_at", "ended_by", "end_reason"])
    other = rel.other_party(by_user)
    if kind == Notification.Kind.MENTOR_LEFT:
        message = f"{by_user} is no longer mentoring, so your mentoring relationship has ended."
    else:
        message = f"Your mentoring relationship with {by_user} has ended."
    if other.pk == rel.mentee_id:
        message += " You can choose another mentor whenever you like."
    _notify(other, kind, message, rel)


@transaction.atomic
def end_relationship(rel, by_user, reason=""):
    """Either party can end a relationship at any time, no reason required."""
    rel = MentoringRelationship.objects.select_for_update().get(pk=rel.pk)
    if not rel.involves(by_user):
        raise MentoringError("You are not part of this mentoring relationship.")
    if not rel.is_active:
        return rel
    if rel.started_at <= active_cutoff():
        _expire(rel, timezone.now())
        return rel
    _end(rel, by_user, reason)
    return rel


@transaction.atomic
def expire_user_relationships(user, now=None):
    """End only this user's relationships past the 4-month limit. No cron needed.

    Called lazily from reads/writes touching that user, so expiry happens
    automatically on next page load. Returns count expired.
    """
    now = now or timezone.now()
    cutoff = active_cutoff(now)
    qs = MentoringRelationship.objects.filter(
        Q(mentor=user) | Q(mentee=user), status=ACTIVE, started_at__lte=cutoff
    )
    ids = list(qs.values_list("pk", flat=True))
    for pk in ids:
        rel = MentoringRelationship.objects.select_for_update().get(pk=pk)
        if rel.is_active and rel.started_at <= cutoff:
            _expire(rel, now)
    return len(ids)


def _expire(rel, now):
    """End one relationship because it reached the 4-month limit. Notifies both parties."""
    rel.status = MentoringRelationship.Status.ENDED
    rel.ended_at = now
    rel.ended_by = None
    rel.end_reason = EXPIRED
    rel.save(update_fields=["status", "ended_at", "ended_by", "end_reason"])
    _notify(
        rel.mentor,
        Notification.Kind.MATCH_ENDED,
        f"Your mentoring relationship with {rel.mentee} ended automatically after 4 months.",
        rel,
    )
    _notify(
        rel.mentee,
        Notification.Kind.MATCH_ENDED,
        f"Your mentoring relationship with {rel.mentor} ended automatically after 4 months."
        " You can choose another mentor whenever you like.",
        rel,
    )


@transaction.atomic
def expire_old_relationships(now=None):
    """End every active relationship older than the 4-month limit. Returns count.

    Only needed for batch cleanup / cron. Normal reads already expire lazily
    via expire_user_relationships(), so no maintenance is required.
    """
    now = now or timezone.now()
    cutoff = now - relationship_duration()
    expired_ids = list(
        MentoringRelationship.objects.filter(status=ACTIVE, started_at__lte=cutoff).values_list(
            "pk", flat=True
        )
    )
    for pk in expired_ids:
        rel = MentoringRelationship.objects.select_for_update().get(pk=pk)
        if rel.is_active and rel.started_at <= cutoff:
            _expire(rel, now)
    return len(expired_ids)


# --- Mentor pool -------------------------------------------------------------


def _validate_capacity(capacity, active_count=0):
    if not 1 <= capacity <= settings.MAX_MENTEES_PER_MENTOR:
        raise MentoringError(
            f"You can mentor between 1 and {settings.MAX_MENTEES_PER_MENTOR} people."
        )
    if capacity < active_count:
        raise MentoringError(
            f"You are mentoring {active_count} people; end a relationship before lowering your places."
        )


@transaction.atomic
def become_mentor(user, *, capacity, contact_preference, superpower, slack_handle="", superpower_other=""):
    """Join the mentor pool, or update settings if already in it."""
    profile = _locked_profile(user)
    active_count = profile.active_mentee_count if profile else 0
    _validate_capacity(capacity, active_count)
    if profile is None:
        profile = MentorProfile(user=user)
    profile.capacity = capacity
    profile.contact_preference = contact_preference
    profile.slack_handle = slack_handle.strip()
    profile.superpower = superpower
    profile.superpower_other = superpower_other.strip() if superpower == MentorProfile.Superpower.OTHER else ""
    if profile.status == MentorProfile.Status.LEFT:
        profile.status = MentorProfile.Status.ACTIVE
    profile.save()
    return profile


def _set_status(user, from_status, to_status):
    with transaction.atomic():
        profile = _locked_profile(user)
        if profile is None or profile.status != from_status:
            return profile
        profile.status = to_status
        profile.save(update_fields=["status", "updated_at"])
        return profile


def pause_mentoring(user):
    """Stop appearing in discovery; existing relationships continue."""
    return _set_status(user, MentorProfile.Status.ACTIVE, MentorProfile.Status.PAUSED)


def resume_mentoring(user):
    return _set_status(user, MentorProfile.Status.PAUSED, MentorProfile.Status.ACTIVE)


@transaction.atomic
def stop_mentoring(user):
    """Leave the mentor pool and end every relationship where `user` is the mentor."""
    expire_user_relationships(user)
    profile = _locked_profile(user)
    if profile is None or not profile.is_participating:
        return
    profile.status = MentorProfile.Status.LEFT
    profile.save(update_fields=["status", "updated_at"])
    for rel in MentoringRelationship.objects.select_for_update().filter(mentor=user, status=ACTIVE):
        _end(rel, user, kind=Notification.Kind.MENTOR_LEFT)


@transaction.atomic
def leave_program(user):
    """End everything: stop mentoring and end the relationship with the user's own mentor."""
    stop_mentoring(user)
    for rel in MentoringRelationship.objects.select_for_update().filter(mentee=user, status=ACTIVE):
        _end(rel, user)
