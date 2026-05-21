import requests
from bs4 import BeautifulSoup
from datetime import datetime
from app.models.resources import ResearchReport
from typing import List
import re
import json
import os

class MiraeResearchCrawler:
    _BASE_URL_TEMPLATE = "https://securities.miraeasset.com/bbs/board/message/list.do?categoryId={}"
    _VIEW_BYPASS_URL_TEMPLATE = (
        "https://securities.miraeasset.com/bbs/board/message/view.do"
        "?messageId={{}}&messageNumber={{}}&categoryId={}"
        "&searchStartYear=2024&searchStartMonth=01&searchStartDay=01"
        "&searchEndYear=2026&searchEndMonth=12&searchEndDay=31"
    )

    def __init__(self, category_id: int = 1521):
        self.BASE_URL = self._BASE_URL_TEMPLATE.format(category_id)
        self.VIEW_BYPASS_URL = self._VIEW_BYPASS_URL_TEMPLATE.format(category_id)
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
        }
        self.db_path = "data/research_db.json"
        os.makedirs("data", exist_ok=True)
        
    def _parse_row(self, row) -> ResearchReport:
        """Helper to parse a single row of the report table."""
        cols = row.find_all('td')
        if len(cols) < 4:
            return None
            
        date_str = cols[0].get_text(strip=True)
        try:
            report_date = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            report_date = datetime.now()
            
        title_td = cols[1]
        title_a = title_td.find('a')
        if not title_a:
            return None
            
        href = title_a.get('href', '')
        match = re.search(r"view\('(\d+)','(\d+)'\)", href)
        if match:
            message_id = match.group(1)
            message_number = match.group(2)
            source_url = self.VIEW_BYPASS_URL.format(message_id, message_number)
            report_id = f"mirae_{message_id}"
        else:
            source_url = ""
            report_id = f"mirae_unknown_{date_str}"
            
        full_title = title_a.get_text(separator=" ", strip=True)
        author_str = cols[3].get_text(strip=True)
        
        attach_td = cols[2]
        attach_a = attach_td.find('a')
        attachment_urls = []
        if attach_a and 'downConfirm(' in attach_a.get('href', ''):
            pdf_href = attach_a.get('href', '')
            pdf_match = re.search(r"downConfirm\('(https?://[^']+)", pdf_href)
            if pdf_match:
                attachment_urls.append(pdf_match.group(1))
        
        return ResearchReport(
            report_id=report_id,
            title=full_title,
            date=report_date,
            author=author_str,
            report_type="Daily Market / Theme",
            source_url=source_url,
            attachment_urls=attachment_urls
        )

    def fetch_recent_reports(self, limit: int = 10) -> List[ResearchReport]:
        """Fetches the most recent research reports from the board."""
        response = requests.get(self.BASE_URL, headers=self.headers)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        tables = soup.find_all('table')
        
        if len(tables) < 2:
            raise ValueError("Could not find the report list table on the page.")
            
        list_table = tables[1]
        rows = list_table.find('tbody').find_all('tr')
        
        reports = []
        for row in rows[:limit]:
            report = self._parse_row(row)
            if report:
                reports.append(report)
                
        return reports

    def fetch_reports_in_range(self, start_date: datetime, end_date: datetime, max_pages: int = 50) -> List[ResearchReport]:
        """Fetches reports between two dates by paginating."""
        reports = []
        cur_page = 1
        
        while cur_page <= max_pages:
            print(f"Fetching page {cur_page}...")
            url = f"{self.BASE_URL}&curPage={cur_page}"
            response = requests.get(url, headers=self.headers)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            tables = soup.find_all('table')
            if len(tables) < 2:
                break
                
            list_table = tables[1]
            rows = list_table.find('tbody').find_all('tr')
            if not rows or "내용이 없습니다" in rows[0].get_text():
                break
                
            for row in rows:
                report = self._parse_row(row)
                if not report:
                    continue
                
                if report.date > end_date:
                    continue
                if report.date < start_date:
                    return reports
                    
                reports.append(report)
            
            cur_page += 1
            
        return reports

    def save_reports(self, reports: List[ResearchReport]):
        """Persists reports to a JSON file, keeping history."""
        existing = self.load_all_reports()
        existing_ids = {r.report_id for r in existing}
        
        new_count = 0
        for r in reports:
            if r.report_id not in existing_ids:
                existing.append(r)
                new_count += 1
                
        # Sort by date descending
        existing.sort(key=lambda x: x.date, reverse=True)
        
        with open(self.db_path, "w", encoding="utf-8") as f:
            json.dump([r.dict() for r in existing], f, ensure_ascii=False, indent=2, default=str)
        return new_count

    def load_all_reports(self) -> List[ResearchReport]:
        """Loads all stored reports from the JSON file."""
        if not os.path.exists(self.db_path):
            return []
        try:
            with open(self.db_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return [ResearchReport(**item) for item in data]
        except Exception:
            return []

    def download_attachments(self, report: ResearchReport, download_dir: str = "research_reports"):
        """Downloads all PDF attachments for a given report."""
        if not report.attachment_urls:
            return []
            
        os.makedirs(download_dir, exist_ok=True)
        downloaded_paths = []
        
        # Sanitize title for filename
        clean_title = re.sub(r'[^\w\s-]', '', report.title).strip()
        clean_title = re.sub(r'[-\s]+', '_', clean_title)
        
        for idx, url in enumerate(report.attachment_urls):
            try:
                # Add index if multiple attachments
                suffix = f"_{idx}" if len(report.attachment_urls) > 1 else ""
                filename = f"{report.date.strftime('%Y%m%d')}_{clean_title}{suffix}.pdf"
                filepath = os.path.join(download_dir, filename)
                
                # Skip if already exists
                if os.path.exists(filepath):
                    downloaded_paths.append(filepath)
                    continue
                
                response = requests.get(url, headers=self.headers, stream=True)
                response.raise_for_status()
                
                with open(filepath, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                
                downloaded_paths.append(filepath)
            except Exception as e:
                print(f"Error downloading attachment from {report.title}: {e}")
                
        return downloaded_paths

if __name__ == "__main__":
    crawler = MiraeResearchCrawler()
    reports = crawler.fetch_recent_reports(2)
    for r in reports:
        print(f"[{r.date.strftime('%Y-%m-%d')}] {r.title} by {r.author}")
        if r.attachment_urls:
            print(f" PDF: {r.attachment_urls[0]}")
