from django.test import TestCase
from django.contrib.admin.sites import AdminSite
from .models import FootballFixture, League, Team
from .admin import FootballFixtureAdmin

# Create your tests here.

class FootballFixtureAdminTestCase(TestCase):
    """Test cases for FootballFixture admin configuration."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.site = AdminSite()
        self.admin = FootballFixtureAdmin(FootballFixture, self.site)
        
        # Create test data
        self.league = League.objects.create(
            name="Test League",
            api_id="test_league_1",
            sport_key="soccer"
        )
        self.home_team = Team.objects.create(name="Home Team")
        self.away_team = Team.objects.create(name="Away Team")
    
    def test_fixture_str_with_date(self):
        """Test __str__ method works when match_date is set."""
        fixture = FootballFixture.objects.create(
            league=self.league,
            home_team=self.home_team,
            away_team=self.away_team,
            match_date="2024-01-15 15:00:00"
        )
        self.assertIn("Home Team vs Away Team", str(fixture))
        self.assertIn("2024-01-15", str(fixture))
    
    def test_fixture_str_without_date(self):
        """Test __str__ method works when match_date is None."""
        fixture = FootballFixture.objects.create(
            league=self.league,
            home_team=self.home_team,
            away_team=self.away_team,
            match_date=None
        )
        result = str(fixture)
        self.assertIn("Home Team vs Away Team", result)
        self.assertIn("TBD", result)
    
    def test_fixture_display_method_exists(self):
        """Test that fixture_display method exists in admin."""
        self.assertTrue(hasattr(self.admin, 'fixture_display'))
    
    def test_list_display_does_not_contain_str(self):
        """Test that list_display doesn't contain __str__ directly."""
        self.assertNotIn('__str__', self.admin.list_display)
        self.assertIn('fixture_display', self.admin.list_display)

