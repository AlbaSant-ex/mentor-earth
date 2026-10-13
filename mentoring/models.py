from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F, Q


class MentorProfile(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Available"
        PAUSED = "paused", "Paused"
        LEFT = "left", "Not mentoring"

    class Contact(models.TextChoices):
        EMAIL = "email", "Email"
        SLACK = "slack", "Slack"
        EITHER = "either", "Either"

    class Superpower(models.TextChoices):
        THINKING = "thinking", "🧠 Thinking"
        COFFEE = "coffee", "☕ Coffee"
        READING = "reading", "📚 Reading papers"
        DEBUGGING = "debugging", "💻 Debugging"
        EXPLAINING = "explaining", "🗣 Explaining things"
        OTHER = "other", "✨ Other"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="mentor_profile"
    )
    # The upper bound is settings.MAX_MENTEES_PER_MENTOR, enforced in services.
    capacity = models.PositiveSmallIntegerField(default=1, validators=[MinValueValidator(1)])
    contact_preference = models.CharField(max_length=10, choices=Contact.choices, default=Contact.EMAIL)
    slack_handle = models.CharField(max_length=60, blank=True)
    superpower = models.CharField(max_length=20, choices=Superpower.choices)
    superpower_other = models.CharField(max_length=40, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(capacity__gte=1), name="mentor_capacity_positive"),
        ]

    def __str__(self):
        return f"Mentor: {self.user}"

    @property
    def superpower_display(self):
        if self.superpower == self.Superpower.OTHER and self.superpower_other:
            return f"✨ {self.superpower_other}"
        return self.get_superpower_display()

    @property
    def active_mentee_count(self):
        if hasattr(self, "n_active"):
            return self.n_active
        from datetime import timedelta

        from django.conf import settings as django_settings
        from django.utils import timezone as tz

        duration_days = getattr(django_settings, "MENTORING_RELATIONSHIP_DURATION_DAYS", 120)
        cutoff = tz.now() - timedelta(days=duration_days)
        return MentoringRelationship.objects.filter(
            mentor_id=self.user_id,
            status=MentoringRelationship.Status.ACTIVE,
            started_at__gt=cutoff,
        ).count()

    @property
    def free_places(self):
        return max(self.capacity - self.active_mentee_count, 0)

    @property
    def is_participating(self):
        return self.status != self.Status.LEFT

    @property
    def is_available(self):
        return self.status == self.Status.ACTIVE and self.free_places > 0

    @property
    def shows_email(self):
        return self.contact_preference in (self.Contact.EMAIL, self.Contact.EITHER)

    @property
    def shows_slack(self):
        return self.contact_preference in (self.Contact.SLACK, self.Contact.EITHER) and bool(
            self.slack_handle
        )


class MentoringRelationship(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        ENDED = "ended", "Ended"

    class EndReason(models.TextChoices):
        GOALS = "goals", "Goals achieved"
        MATCH = "match", "Not the right match"
        AVAILABILITY = "availability", "Availability changed"
        EXPIRED = "expired", "Completed (4 months)"
        OTHER = "other", "Other"

    mentor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="mentoring_as_mentor"
    )
    mentee = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="mentoring_as_mentee"
    )
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    ended_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    end_reason = models.CharField(max_length=20, choices=EndReason.choices, blank=True)

    class Meta:
        ordering = ["-started_at"]
        constraints = [
            models.CheckConstraint(condition=~Q(mentor=F("mentee")), name="no_self_mentoring"),
            models.UniqueConstraint(
                fields=["mentee"], condition=Q(status="active"), name="one_active_mentor_per_mentee"
            ),
            models.UniqueConstraint(
                fields=["mentor", "mentee"], condition=Q(status="active"), name="unique_active_pair"
            ),
        ]

    def __str__(self):
        return f"{self.mentor} → {self.mentee} ({self.status})"

    @property
    def is_active(self):
        return self.status == self.Status.ACTIVE

    @property
    def expires_at(self):
        """When this relationship ends automatically (~4 months after start)."""
        from datetime import timedelta

        from django.conf import settings as django_settings
        from django.utils import timezone as tz

        duration_days = getattr(django_settings, "MENTORING_RELATIONSHIP_DURATION_DAYS", 120)
        started = self.started_at or tz.now()
        return started + timedelta(days=duration_days)

    @property
    def is_expired(self):
        from django.utils import timezone as tz

        return self.is_active and tz.now() >= self.expires_at

    @property
    def days_remaining(self):
        from django.utils import timezone as tz

        return max((self.expires_at - tz.now()).days, 0)

    def other_party(self, user):
        return self.mentee if user.pk == self.mentor_id else self.mentor

    def involves(self, user):
        return user.pk in (self.mentor_id, self.mentee_id)


class Notification(models.Model):
    class Kind(models.TextChoices):
        MATCH_CREATED = "match_created", "New match"
        MATCH_ENDED = "match_ended", "Match ended"
        MENTOR_LEFT = "mentor_left", "Mentor left"

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications"
    )
    kind = models.CharField(max_length=20, choices=Kind.choices)
    message = models.CharField(max_length=300)
    relationship = models.ForeignKey(
        MentoringRelationship, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.recipient}: {self.message}"

    @property
    def icon(self):
        return "🎉" if self.kind == self.Kind.MATCH_CREATED else "👋"
