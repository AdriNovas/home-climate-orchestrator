"""Overnight permission is explicit configuration, not truthy input."""
import pathlib,sys,unittest
sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]/'custom_components/climate_orchestrator'))
from domain.models import Zone
class NightPermission(unittest.TestCase):
 def test_boolean_only(self):
  for value in ['false','true',0,1,None]:
   with self.subTest(value=value),self.assertRaises(ValueError):
    Zone('room','Room','plant','sensor.demo',night_allowed=value)
  for value in [False,True]:
   self.assertIs(Zone('room','Room','plant','sensor.demo',night_allowed=value).night_allowed,value)
