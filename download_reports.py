import os
import sys
from datetime import datetime

# Adjust path to include the app directory
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__))))

from app.core.adapters.research_crawler import MiraeResearchCrawler

def main():
    print("=== Mirae Asset Research Downloader ===")
    crawler = MiraeResearchCrawler()
    
    # 1. Fetch recent reports
    print("Fetching recent reports from Mirae Asset...")
    try:
        all_reports = crawler.fetch_recent_reports(limit=40)
    except Exception as e:
        print(f"Error fetching reports: {e}")
        return

    # 2. Save to database (returns number of new reports)
    new_count = crawler.save_reports(all_reports)
    print(f"Discovered {len(all_reports)} reports ({new_count} new).")

    if len(all_reports) == 0:
        print("No reports found.")
        return

    # 3. Download attachments for recent reports
    print("\nStarting downloads to research_reports/ ...")
    total_downloaded = 0
    # Process reports from the last 7 days or at least the top 10
    for report in all_reports[:15]:
        if report.attachment_urls:
            print(f"Processing: {report.title} ({report.date.strftime('%Y-%m-%d')})")
            paths = crawler.download_attachments(report)
            if paths:
                total_downloaded += len(paths)
    
    print(f"\nFinished. Total files checked/downloaded: {total_downloaded}")
    print(f"Check the 'research_reports' folder for the PDF materials.")

if __name__ == "__main__":
    main()
