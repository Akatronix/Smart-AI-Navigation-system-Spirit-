import logging
import os
import requests
from config.settings import GOOGLE_MAPS_API_KEY

logger = logging.getLogger("spirit.maps")


class MapsClient:
    def __init__(self):
        self.api_key = GOOGLE_MAPS_API_KEY
        self.enabled = bool(self.api_key)
        if not self.enabled:
            logger.info("No Google Maps API key — location features disabled.")
        else:
            logger.info("Google Maps API key loaded.")

    def reverse_geocode(self, lat: float, lon: float) -> str:
        """Convert GPS coordinates to a human-readable address."""
        if not self.enabled:
            return None
        
        try:
            url = "https://maps.googleapis.com/maps/api/geocode/json"
            params = {
                "latlng": f"{lat},{lon}",
                "key": self.api_key,
            }
            resp = requests.get(url, params=params, timeout=5)
            resp.raise_for_status()
            data = resp.json()
            
            if data.get("status") == "OK" and data.get("results"):
                # Return the formatted address
                return data["results"][0].get("formatted_address", "")
            return None
        except Exception as e:
            logger.error("Reverse geocode failed: %s", e)
            return None

    def get_walking_directions(self, origin_lat: float, origin_lon: float, 
                                destination: str) -> str:
        """Get walking directions from current location to destination."""
        if not self.enabled:
            return None
        
        try:
            # First, geocode the destination
            geocode_url = "https://maps.googleapis.com/maps/api/geocode/json"
            geocode_resp = requests.get(geocode_url, params={
                "address": destination,
                "key": self.api_key,
            }, timeout=5)
            geocode_resp.raise_for_status()
            geocode_data = geocode_resp.json()
            
            if geocode_data.get("status") != "OK" or not geocode_data.get("results"):
                return None
            
            dest_lat = geocode_data["results"][0]["geometry"]["location"]["lat"]
            dest_lon = geocode_data["results"][0]["geometry"]["location"]["lng"]
            
            # Get directions
            directions_url = "https://maps.googleapis.com/maps/api/directions/json"
            directions_resp = requests.get(directions_url, params={
                "origin": f"{origin_lat},{origin_lon}",
                "destination": f"{dest_lat},{dest_lon}",
                "mode": "walking",
                "key": self.api_key,
            }, timeout=10)
            directions_resp.raise_for_status()
            directions_data = directions_resp.json()
            
            if directions_data.get("status") != "OK" or not directions_data.get("routes"):
                return None
            
            # Extract step-by-step directions
            route = directions_data["routes"][0]
            legs = route.get("legs", [])
            if not legs:
                return None
            
            steps = []
            total_distance = legs[0].get("distance", {}).get("text", "unknown")
            total_duration = legs[0].get("duration", {}).get("text", "unknown")
            
            for step in legs[0].get("steps", []):
                instruction = step.get("html_instructions", "")
                # Strip HTML tags
                import re
                instruction = re.sub(r'<[^>]+>', '', instruction)
                distance = step.get("distance", {}).get("text", "")
                steps.append(f"- {instruction} ({distance})")
            
            # Build summary
            summary = f"Total: {total_distance}, about {total_duration}.\n"
            summary += "\n".join(steps[:10])  # Limit to 10 steps
            if len(steps) > 10:
                summary += f"\n... and {len(steps) - 10} more steps"
            
            return summary
            
        except Exception as e:
            logger.error("Directions failed: %s", e)
            return None