from typing import Dict, List, Any, Optional
import json
import os
import csv
from datetime import datetime

class ResultProcessor:
    """Class for processing and saving scraped data."""
    
    def __init__(self, output_dir: str = "output"):
        """
        Initialize the result processor.
        
        Args:
            output_dir: Directory to save output files
        """
        self.output_dir = output_dir
        self._ensure_output_dir()
    
    def _ensure_output_dir(self):
        """Ensure the output directory exists."""
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)
    
    def save_to_json(self, data: List[Dict[str, Any]], filename: str) -> str:
        """
        Save data to a JSON file.
        
        Args:
            data: Data to save
            filename: Base filename (without extension)
            
        Returns:
            Path to the saved file
        """
        self._ensure_output_dir()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_path = os.path.join(self.output_dir, f"{filename}_{timestamp}.json")
        
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        return file_path
    
    def save_to_csv(self, data: List[Dict[str, Any]], filename: str, 
                   columns: Optional[List[str]] = None) -> str:
        """
        Save data to a CSV file.
        
        Args:
            data: Data to save
            filename: Base filename (without extension)
            columns: List of columns to include (defaults to all keys in the first data item)
            
        Returns:
            Path to the saved file
        """
        if not data:
            return ""
            
        self._ensure_output_dir()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_path = os.path.join(self.output_dir, f"{filename}_{timestamp}.csv")
        
        # Determine columns if not provided
        if not columns:
            columns = list(data[0].keys())
        
        with open(file_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=columns)
            writer.writeheader()
            
            for item in data:
                # Filter to only include specified columns
                row = {k: item.get(k, '') for k in columns}
                writer.writerow(row)
        
        return file_path
    
    def filter_results(self, data: List[Dict[str, Any]], 
                      filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Filter results based on criteria.
        
        Args:
            data: Data to filter
            filters: Dictionary of field-value pairs to filter on
            
        Returns:
            Filtered data
        """
        filtered_data = data
        
        for field, value in filters.items():
            if isinstance(value, list):
                # Filter for any value in the list
                filtered_data = [item for item in filtered_data 
                              if field in item and item[field] in value]
            else:
                # Exact match filter
                filtered_data = [item for item in filtered_data 
                              if field in item and item[field] == value]
        
        return filtered_data
    
    def sort_results(self, data: List[Dict[str, Any]], 
                    sort_by: str, ascending: bool = True) -> List[Dict[str, Any]]:
        """
        Sort results based on a field.
        
        Args:
            data: Data to sort
            sort_by: Field to sort on
            ascending: Whether to sort in ascending order
            
        Returns:
            Sorted data
        """
        return sorted(data, key=lambda x: x.get(sort_by, ''), reverse=not ascending)
    
    def deduplicate_results(self, data: List[Dict[str, Any]], 
                         key_field: str) -> List[Dict[str, Any]]:
        """
        Remove duplicate results based on a key field.
        
        Args:
            data: Data to deduplicate
            key_field: Field to use as the unique key
            
        Returns:
            Deduplicated data
        """
        seen = set()
        deduped_data = []
        
        for item in data:
            if key_field in item:
                key = item[key_field]
                if key not in seen:
                    seen.add(key)
                    deduped_data.append(item)
            else:
                # If the item doesn't have the key field, keep it
                deduped_data.append(item)
        
        return deduped_data 