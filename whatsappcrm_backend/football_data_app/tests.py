from django.test import TestCase
from django.contrib.admin.sites import AdminSite
from django.utils import timezone
from datetime import timedelta, datetime
from .models import FootballFixture, League, Team, Bookmaker, Market, MarketCategory, MarketOutcome
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
            # A real datetime, not a string -- Model.objects.create() doesn't
            # coerce field values via to_python() the way a ModelForm would,
            # so a raw string stored on a DateTimeField stays a str in memory
            # until the instance is reloaded from the DB, and __str__() calls
            # .strftime() on it directly.
            match_date=timezone.make_aware(datetime(2024, 1, 15, 15, 0, 0))
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


class OddsAggregationTestCase(TestCase):
    """Test cases for odds aggregation logic using median instead of highest."""
    
    def setUp(self):
        """Set up test data for odds aggregation."""
        # Create league
        self.league = League.objects.create(
            name="Premier League",
            api_id="epl",
            sport_key="soccer"
        )
        
        # Create teams
        self.home_team = Team.objects.create(name="Manchester United")
        self.away_team = Team.objects.create(name="Liverpool")
        
        # Create fixture
        self.fixture = FootballFixture.objects.create(
            league=self.league,
            home_team=self.home_team,
            away_team=self.away_team,
            match_date=timezone.now() + timedelta(days=1),
            status=FootballFixture.FixtureStatus.SCHEDULED
        )
        
        # Create bookmakers
        self.bookmaker1 = Bookmaker.objects.create(
            name="Bookmaker 1",
            api_bookmaker_key="bm1"
        )
        self.bookmaker2 = Bookmaker.objects.create(
            name="Bookmaker 2", 
            api_bookmaker_key="bm2"
        )
        self.bookmaker3 = Bookmaker.objects.create(
            name="Bookmaker 3",
            api_bookmaker_key="bm3"
        )
        
        # Create market category
        self.category = MarketCategory.objects.create(
            name="Match Winner"
        )
    
    def test_median_odds_calculation(self):
        """Test that median odds are used instead of highest odds."""
        # Create markets for the same fixture from different bookmakers
        # With different odds for the same outcome
        
        # Bookmaker 1: Manchester United win @ 2.00
        market1 = Market.objects.create(
            fixture=self.fixture,
            bookmaker=self.bookmaker1,
            category=self.category,
            api_market_key="h2h",
            last_updated_odds_api=timezone.now(),
            is_active=True
        )
        outcome1 = MarketOutcome.objects.create(
            market=market1,
            outcome_name="Manchester United",
            odds=2.00,
            is_active=True
        )
        
        # Bookmaker 2: Manchester United win @ 2.10 (median)
        market2 = Market.objects.create(
            fixture=self.fixture,
            bookmaker=self.bookmaker2,
            category=self.category,
            api_market_key="h2h",
            last_updated_odds_api=timezone.now(),
            is_active=True
        )
        outcome2 = MarketOutcome.objects.create(
            market=market2,
            outcome_name="Manchester United",
            odds=2.10,
            is_active=True
        )
        
        # Bookmaker 3: Manchester United win @ 5.00 (outlier - too high)
        market3 = Market.objects.create(
            fixture=self.fixture,
            bookmaker=self.bookmaker3,
            category=self.category,
            api_market_key="h2h",
            last_updated_odds_api=timezone.now(),
            is_active=True
        )
        outcome3 = MarketOutcome.objects.create(
            market=market3,
            outcome_name="Manchester United",
            odds=5.00,
            is_active=True
        )
        
        # Import the function to test
        from .utils import get_formatted_football_data
        
        # Get formatted data
        result = get_formatted_football_data(
            data_type="scheduled_fixtures",
            league_code="epl",
            days_ahead=2
        )
        
        # Not assertIsNotNone alone -- an empty list is also "not None" and
        # would silently skip every assertion below via the old `if result:`
        # guard, letting a regression that returns no fixtures pass unnoticed.
        self.assertTrue(result, "Function should return data for scheduled fixtures")

        result_text = ' '.join(result)
        # Check that fixture is present
        self.assertIn("Manchester United vs Liverpool", result_text)
        # The median of [2.00, 2.10, 5.00] is 2.10 -- check the true median is
        # shown, not the min (2.00) or the outlier (5.00). Accepting "2.0" here
        # too would let an implementation that picked the min instead of the
        # median pass just as well, since "2.0" is also a substring of "2.00".
        self.assertIn("2.10", result_text)
        self.assertNotIn("5.00", result_text)

