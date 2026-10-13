from django.core.management.base import BaseCommand

from mentoring import services


class Command(BaseCommand):
    help = "End mentoring relationships older than 4 months."

    def handle(self, *args, **options):
        count = services.expire_old_relationships()
        self.stdout.write(f"Expired {count} relationship(s).")
