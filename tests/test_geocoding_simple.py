#!/usr/bin/env python3
"""
Minimal test for geocoding functionality - tests just the core functions.
"""

import logging

# Set up basic logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_location_info(latitude: float, longitude: float) -> dict:
    """
    Get location information from coordinates using reverse geocoding.
    Provides robust fallback handling for various failure scenarios.
    """
    # Default fallback values based on common coordinates
    fallback_info = {
        "city": "Unknown",
        "state": "Unknown", 
        "country": "Unknown",
        "country_code": "UNK",
        "wmo_id": "999999"
    }
    
    # Try to determine rough region from coordinates for better fallbacks
    if 35.0 <= latitude <= 42.0 and 19.0 <= longitude <= 28.0:
        # Greece region
        fallback_info.update({
            "city": "Greece_Location",
            "state": "Greece", 
            "country": "Greece",
            "country_code": "GRC",
            "wmo_id": "167140"  # Thessaloniki WMO ID
        })
    elif 40.0 <= latitude <= 45.0 and 19.0 <= longitude <= 30.0:
        # Balkans region
        fallback_info.update({
            "city": "Balkans_Location",
            "state": "Balkans",
            "country": "Balkan_Region", 
            "country_code": "EUR",
            "wmo_id": "150000"
        })
    
    try:
        # Attempt reverse geocoding with geopy
        from geopy.geocoders import Nominatim
        from geopy.exc import GeocoderTimedOut, GeocoderUnavailable, GeocoderServiceError
        
        # Initialize with user agent and timeout
        geolocator = Nominatim(
            user_agent="energy_comfort_tool_epw_generator/1.0",
            timeout=10
        )
        
        logger.info(f"Attempting reverse geocoding for coordinates: {latitude:.4f}, {longitude:.4f}")
        
        # Perform reverse geocoding
        location = geolocator.reverse(f"{latitude}, {longitude}", language='en')
        
        if location and location.raw:
            address = location.raw.get('address', {})
            
            # Extract location components with fallbacks
            city = (address.get('city') or 
                   address.get('town') or 
                   address.get('village') or 
                   address.get('municipality') or
                   fallback_info['city'])
            
            state = (address.get('state') or 
                    address.get('region') or 
                    address.get('province') or
                    address.get('county') or
                    fallback_info['state'])
            
            country = address.get('country', fallback_info['country'])
            
            # Map country to ISO 3-letter code with fallbacks
            country_code = _get_country_code(country, fallback_info['country_code'])
            
            # Generate WMO-like ID from coordinates (not real WMO but valid format)
            wmo_id = _generate_wmo_id(latitude, longitude)
            
            result = {
                "city": city,
                "state": state,
                "country": country,
                "country_code": country_code,
                "wmo_id": wmo_id
            }
            
            logger.info(f"Reverse geocoding successful: {result}")
            return result
            
        else:
            logger.warning("Reverse geocoding returned no results, using fallback")
            
    except (GeocoderTimedOut, GeocoderUnavailable, GeocoderServiceError) as e:
        logger.warning(f"Geocoding service error: {e}, using fallback")
    except ImportError:
        logger.warning("geopy package not available, using fallback location info")
    except Exception as e:
        logger.warning(f"Unexpected error in reverse geocoding: {e}, using fallback")
    
    # Generate WMO-like ID even for fallback
    fallback_info['wmo_id'] = _generate_wmo_id(latitude, longitude)
    logger.info(f"Using fallback location info: {fallback_info}")
    return fallback_info


def _get_country_code(country_name: str, fallback: str = "UNK") -> str:
    """Convert country name to 3-letter ISO code with fallbacks."""
    country_mapping = {
        'greece': 'GRC',
        'united states': 'USA', 
        'united kingdom': 'GBR',
        'germany': 'DEU',
        'france': 'FRA',
        'italy': 'ITA',
        'spain': 'ESP',
        'turkey': 'TUR',
        'bulgaria': 'BGR',
        'serbia': 'SRB',
        'albania': 'ALB',
        'north macedonia': 'MKD',
        'montenegro': 'MNE',
        'bosnia and herzegovina': 'BIH',
        'croatia': 'HRV',
        'slovenia': 'SVN',
    }
    
    country_lower = country_name.lower()
    return country_mapping.get(country_lower, fallback)


def _generate_wmo_id(latitude: float, longitude: float) -> str:
    """Generate a WMO-like 6-digit identifier from coordinates."""
    # Create a pseudo-WMO ID based on coordinates
    # Format: RRLLLL where RR is region code, LLLL is location-specific
    
    # Determine region code based on rough geographic regions
    if 35.0 <= latitude <= 70.0 and -10.0 <= longitude <= 50.0:
        region = "16"  # Europe
    elif 25.0 <= latitude <= 50.0 and 25.0 <= longitude <= 145.0:
        region = "38"  # Asia
    elif -40.0 <= latitude <= 40.0 and -20.0 <= longitude <= 55.0:
        region = "60"  # Africa
    elif 15.0 <= latitude <= 85.0 and -180.0 <= longitude <= -50.0:
        region = "70"  # North America
    elif -60.0 <= latitude <= 15.0 and -85.0 <= longitude <= -30.0:
        region = "80"  # South America
    else:
        region = "99"  # Other/Ocean
    
    # Generate location-specific 4-digit code from coordinates
    lat_code = int(abs(latitude * 100) % 100)
    lon_code = int(abs(longitude * 100) % 100) 
    location_code = f"{lat_code:02d}{lon_code:02d}"
    
    return f"{region}{location_code}"


def create_location_header(latitude: float, longitude: float) -> str:
    """Create just the LOCATION header line for testing."""
    location_info = get_location_info(latitude, longitude)
    
    return (f"LOCATION,{location_info['city']},{location_info['state']},"
            f"{location_info['country_code']},TMY,{location_info['wmo_id']},"
            f"{latitude:.4f},{longitude:.4f},2.0,50.0")


def test_geocoding():
    """Test the geocoding functionality with various coordinates."""
    
    print("Testing geocoding functionality...\n")
    
    # Test coordinates
    test_coords = [
        (40.6401, 22.9444, "Thessaloniki, Greece"),
        (52.5200, 13.4050, "Berlin, Germany"), 
        (40.7128, -74.0060, "New York, USA"),
        (0.0, 0.0, "Null Island (Ocean)"),
    ]
    
    for lat, lon, description in test_coords:
        print(f"Testing coordinates: {lat:.4f}, {lon:.4f} ({description})")
        
        try:
            # Test location info retrieval
            location_info = get_location_info(lat, lon)
            print(f"  Result: {location_info}")
            
            # Test LOCATION header generation
            location_header = create_location_header(lat, lon)
            print(f"  EPW LOCATION: {location_header}")
            
            # Validate the LOCATION line has correct number of fields
            fields = location_header.split(',')
            if len(fields) == 10:
                print(f"  ✅ LOCATION header has correct 10 fields")
            else:
                print(f"  ❌ LOCATION header has {len(fields)} fields, expected 10")
                print(f"     Fields: {fields}")
            
        except Exception as e:
            print(f"  ❌ Error: {e}")
            import traceback
            traceback.print_exc()
        
        print()


if __name__ == "__main__":
    test_geocoding()
