from unittest.mock import patch

from django.core.files.base import ContentFile
from django.test import TestCase

from bots.models import Bot, BotEventTypes, BotStates, Organization, Participant, Project, Recording, RecordingStates, Utterance


def mock_file_field_delete_sets_name_to_none(instance, save=True):
    """
    A side_effect function for mocking FieldFile.delete.
    Sets the FieldFile's name to None and saves the parent model instance.
    """
    # 'instance' here is the FieldFile instance being deleted
    instance.name = None
    if save:
        # instance.instance refers to the model instance (e.g., Recording)
        # that owns this FieldFile.
        instance.instance.save()


class TestBotDataDeletion(TestCase):
    def setUp(self):
        # Create test organization
        self.organization = Organization.objects.create(name="Test Org")

        # Create test project
        self.project = Project.objects.create(organization=self.organization, name="Test Project")

        # Create two test bots
        self.bot1 = Bot.objects.create(project=self.project, name="Bot One", meeting_url="https://test.com/meeting1", state=BotStates.ENDED)

        self.bot2 = Bot.objects.create(project=self.project, name="Bot Two", meeting_url="https://test.com/meeting2", state=BotStates.ENDED)

        # Create participants for each bot
        self.participant1 = Participant.objects.create(bot=self.bot1, uuid="participant1", full_name="Test Participant 1")

        self.participant2 = Participant.objects.create(bot=self.bot2, uuid="participant2", full_name="Test Participant 2")

        # Create recordings for each bot
        self.recording1 = Recording.objects.create(bot=self.bot1, recording_type=1, transcription_type=1, state=RecordingStates.COMPLETE)
        # Add a file to the recording
        self.recording1.file.save("test1.mp4", ContentFile(b"test content 1"))

        self.recording2 = Recording.objects.create(bot=self.bot2, recording_type=1, transcription_type=1, state=RecordingStates.COMPLETE)
        # Add a file to the recording
        self.recording2.file.save("test2.mp4", ContentFile(b"test content 2"))

        # Create utterances for each recording
        self.utterance1 = Utterance.objects.create(recording=self.recording1, participant=self.participant1, audio_blob=b"test audio 1", timestamp_ms=1000, duration_ms=500)

        self.utterance2 = Utterance.objects.create(recording=self.recording2, participant=self.participant2, audio_blob=b"test audio 2", timestamp_ms=1000, duration_ms=500)

    @patch("django.db.models.fields.files.FieldFile.delete", autospec=True)
    def test_delete_data_deletes_specific_bot_data_only(self, mock_delete):
        """Test that deleting data for one bot doesn't affect other bots"""
        # Verify initial state
        self.assertEqual(Bot.objects.count(), 2)
        self.assertEqual(Participant.objects.count(), 2)
        self.assertEqual(Recording.objects.count(), 2)
        self.assertEqual(Utterance.objects.count(), 2)

        # Delete data for bot1
        self.bot1.delete_data()

        # Verify bot1's data is deleted
        self.assertEqual(Participant.objects.filter(bot=self.bot1).count(), 0)
        self.assertEqual(Utterance.objects.filter(recording__bot=self.bot1).count(), 0)

        # Verify bot2's data is still intact
        self.assertEqual(Participant.objects.filter(bot=self.bot2).count(), 1)
        self.assertEqual(Recording.objects.filter(bot=self.bot2).count(), 1)
        self.assertEqual(Utterance.objects.filter(recording__bot=self.bot2).count(), 1)

        # Verify bot2's state is still ENDED
        self.bot2.refresh_from_db()
        self.assertEqual(self.bot2.state, BotStates.ENDED)

        # Verify bot1's state changed to DATA_DELETED
        self.bot1.refresh_from_db()
        self.assertEqual(self.bot1.state, BotStates.DATA_DELETED)

        # Verify event was created
        event = self.bot1.bot_events.filter(event_type=BotEventTypes.DATA_DELETED).first()
        self.assertIsNotNone(event)
        self.assertEqual(event.old_state, BotStates.ENDED)
        self.assertEqual(event.new_state, BotStates.DATA_DELETED)

    @patch("django.db.models.fields.files.FieldFile.delete", autospec=True)
    def test_delete_data_invalid_state(self, mock_delete):
        """Test that delete_data raises an error if bot is not in a valid state"""
        # Change bot state to one that's not valid for data deletion
        self.bot1.state = BotStates.JOINED_RECORDING
        self.bot1.save()

        # Verify delete_data raises ValueError
        with self.assertRaises(ValueError):
            self.bot1.delete_data()

        # Verify no data was deleted
        self.assertEqual(Participant.objects.filter(bot=self.bot1).count(), 1)
        self.assertEqual(Utterance.objects.filter(recording__bot=self.bot1).count(), 1)

    @patch("django.db.models.fields.files.FieldFile.delete", autospec=True)
    def test_delete_data_multiple_recordings(self, mock_delete):
        mock_delete.side_effect = mock_file_field_delete_sets_name_to_none

        """Test that delete_data deletes data from multiple recordings"""
        # Create another recording for bot1
        recording1b = Recording.objects.create(bot=self.bot1, recording_type=1, transcription_type=1, state=RecordingStates.COMPLETE)
        recording1b.file.save("test1b.mp4", ContentFile(b"test content 1b"))

        # Create utterance for the new recording
        utterance1b = Utterance.objects.create(recording=recording1b, participant=self.participant1, audio_blob=b"test audio 1b", timestamp_ms=2000, duration_ms=500)

        # Initial count
        self.assertEqual(Recording.objects.filter(bot=self.bot1).count(), 2)
        self.assertEqual(Utterance.objects.filter(recording__bot=self.bot1).count(), 2)

        # Delete data for bot1
        self.bot1.delete_data()

        # Verify all of bot1's data is deleted
        self.assertEqual(Utterance.objects.filter(recording__bot=self.bot1).count(), 0)

        # Verify recording files are deleted but records still exist
        self.bot1.refresh_from_db()
        self.assertEqual(Recording.objects.filter(bot=self.bot1).count(), 2)

        # Check files are deleted
        for recording in Recording.objects.filter(bot=self.bot1):
            self.assertFalse(recording.file)

    @patch("django.db.models.fields.files.FieldFile.delete", autospec=True)
    def test_fatal_error_to_data_deleted_transition(self, mock_delete):
        """Test that a bot in FATAL_ERROR state can transition to DATA_DELETED"""
        # Change bot state to FATAL_ERROR
        self.bot1.state = BotStates.FATAL_ERROR
        self.bot1.save()

        # Delete data
        self.bot1.delete_data()

        # Verify state changed to DATA_DELETED
        self.bot1.refresh_from_db()
        self.assertEqual(self.bot1.state, BotStates.DATA_DELETED)
