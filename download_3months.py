import os
import sys
from datetime import datetime, timedelta

# Adjust path to include the app directory
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__))))

from app.core.adapters.research_crawler import MiraeResearchCrawler

def main():
    print("=== Mirae Asset 3-Month Research Downloader ===")
    crawler = MiraeResearchCrawler()
    
    # Define date range: last 90 days
    end_date = datetime.now()
    start_date = end_date - timedelta(days=90)
    
    print(f"Target Range: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
    print("Fetching reports from the last 3 months (paginating if necessary)...")
    
    try:
        # 1. Fetch reports in range
        reports = crawler.fetch_reports_in_range(start_date, end_date)
        print(f"Found {len(reports)} reports in the target range.")
        
        # 2. Save to database
        new_count = crawler.save_reports(reports)
        print(f"Database updated ({new_count} new entries).")
        
        # 3. Download attachments
        if len(reports) > 0:
            print("\nStarting downloads to research_reports/ ...")
            total_files = 0
            for i, report in enumerate(reports):
                if report.attachment_urls:
                    print(f"[{i+1}/{len(reports)}] Downloading: {report.title} ({report.date.strftime('%Y-%m-%d')})")
                    downloaded = crawler.download_attachments(report)
                    total_files += len(downloaded)
                    
            print(f"\nCompleted! Total files processed/downloaded: {total_files}")
            print(f"Materials are available in the 'research_reports' folder.")
        
    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    main()
