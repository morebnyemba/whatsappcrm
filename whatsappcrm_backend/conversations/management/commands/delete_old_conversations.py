# whatsappcrm_backend/conversations/management/commands/delete_old_conversations.py

import logging
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from datetime import timedelta
from django.conf import settings
from django.db import transaction

from conversations.models import Message, Contact # Ensure your models are correctly imported

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Deletes messages older than a specified number of days (defined in settings.CONVERSATION_EXPIRY_DAYS).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--days',
            type=int,
            help='Override the CONVERSATION_EXPIRY_DAYS setting for this run.'
        )
        parser.add_argument(
            '--delete-contacts',
            action='store_true',
            help='Also delete contacts that have no messages left after old messages are deleted and whose last_seen is older than expiry days.'
        )
        parser.add_argument(
            '--batch-size',
            type=int,
            default=1000,
            help='Number of messages to delete in each batch to manage memory usage.'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Simulate the deletion process without actually deleting any data.'
        )

    def handle(self, *args, **options):
        expiry_days = options['days'] if options['days'] is not None else settings.CONVERSATION_EXPIRY_DAYS
        delete_contacts_flag = options['delete_contacts']
        batch_size = options['batch_size']
        dry_run = options['dry_run']

        if expiry_days <= 0:
            raise CommandError("Expiry days must be a positive integer.")

        cutoff_date = timezone.now() - timedelta(days=expiry_days)

        self.stdout.write(self.style.NOTICE(
            f"Starting deletion process for messages older than {expiry_days} days (before {cutoff_date.strftime('%Y-%m-%d %H:%M:%S %Z')})."
        ))
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN active. No data will be deleted."))

        try:
            with transaction.atomic(): # Ensure all or nothing if an error occurs mid-process
                # Delete old messages in batches
                messages_to_delete_qs = Message.objects.filter(timestamp__lt=cutoff_date)
                total_messages_to_delete = messages_to_delete_qs.count()

                if total_messages_to_delete == 0:
                    self.stdout.write(self.style.SUCCESS("No messages found older than the cutoff date."))
                else:
                    self.stdout.write(f"Found {total_messages_to_delete} messages to delete.")
                    
                    deleted_messages_count = 0
                    # Iterating over a queryset with delete() in batches
                    # Slicing creates new querysets, so we loop until no more matching records
                    while True:
                        batch_to_delete_ids = list(messages_to_delete_qs.values_list('id', flat=True)[:batch_size])
                        if not batch_to_delete_ids:
                            break
                        
                        if not dry_run:
                            num_deleted, _ = Message.objects.filter(id__in=batch_to_delete_ids).delete()
                            deleted_messages_count += num_deleted
                        else:
                            # In dry run, just count them as if they were deleted
                            deleted_messages_count += len(batch_to_delete_ids)
                        
                        self.stdout.write(f"Processed batch. Total messages deleted so far: {deleted_messages_count}/{total_messages_to_delete}")
                        if dry_run and deleted_messages_count >= total_messages_to_delete : # Ensure dry run loop terminates
                            break


                    self.stdout.write(self.style.SUCCESS(
                        f"Successfully {'simulated deletion of' if dry_run else 'deleted'} {deleted_messages_count} old messages."
                    ))

                # Optionally, delete contacts with no remaining messages and old last_seen
                if delete_contacts_flag:
                    self.stdout.write(self.style.NOTICE("Checking for contacts to delete..."))
                    # Find contacts whose last_seen is older than the cutoff_date
                    # AND who no longer have any messages (because they were deleted above, or never had any recent ones)
                    
                    # This can be inefficient if there are many contacts.
                    # A more optimized way might involve checking contacts whose messages were all before cutoff.
                    # For now, a simpler approach:
                    contacts_to_check_qs = Contact.objects.filter(last_seen__lt=cutoff_date)
                    
                    deleted_contacts_count = 0
                    total_contacts_eligible_for_check = contacts_to_check_qs.count()
                    
                    if total_contacts_eligible_for_check == 0:
                        self.stdout.write(self.style.SUCCESS("No contacts found with last_seen older than cutoff for deletion check."))
                    else:
                        self.stdout.write(f"Found {total_contacts_eligible_for_check} contacts with last_seen older than cutoff. Checking if they have remaining messages...")
                        
                        # Iterate in batches for contacts as well
                        contact_ids_to_delete = []
                        for contact_batch_ids in self.queryset_iterator(contacts_to_check_qs.values_list('id', flat=True), batch_size):
                            for contact_id in contact_batch_ids:
                                if not Message.objects.filter(contact_id=contact_id).exists():
                                    contact_ids_to_delete.append(contact_id)
                        
                        if contact_ids_to_delete:
                            self.stdout.write(f"Found {len(contact_ids_to_delete)} contacts with no remaining messages and old last_seen.")
                            if not dry_run:
                                num_deleted_contacts, _ = Contact.objects.filter(id__in=contact_ids_to_delete).delete()
                                deleted_contacts_count = num_deleted_contacts
                            else:
                                deleted_contacts_count = len(contact_ids_to_delete)
                            
                            self.stdout.write(self.style.SUCCESS(
                                f"Successfully {'simulated deletion of' if dry_run else 'deleted'} {deleted_contacts_count} old contacts with no messages."
                            ))
                        else:
                            self.stdout.write(self.style.SUCCESS("No contacts met criteria for deletion (all had recent messages or were not old enough)."))
                            
        except Exception as e:
            logger.error(f"An error occurred during old conversation deletion: {e}", exc_info=True)
            raise CommandError(f"Failed to delete old conversations. Error: {e}")

        self.stdout.write(self.style.SUCCESS("Old conversation deletion process finished."))

    def queryset_iterator(self, queryset, chunk_size=1000):
        """
        Iterate over a Django Queryset ordered by the primary key
        in chunks of size `chunk_size`.
        """
        pk = 0
        last_pk = queryset.order_by('-pk')[0] if queryset.exists() else 0
        queryset = queryset.order_by('pk')
        while pk < last_pk:
            chunk = []
            for row in queryset.filter(pk__gt=pk)[:chunk_size]:
                chunk.append(row) # row is already the ID if using values_list('id', flat=True)
                pk = row # pk becomes the last ID in the chunk
            if not chunk: # Avoid infinite loop if queryset becomes empty
                break
            yield chunk

