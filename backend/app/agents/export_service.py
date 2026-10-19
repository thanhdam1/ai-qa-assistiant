import io
import csv
from typing import List
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from app.agents.test_case_agent import TestSuite, TestCase

class ExportService:
    """
    Exports TestSuites to Excel (.xlsx) and CSV
    formatted for Jira Xray, Zephyr, and TestRail.
    """

    @classmethod
    def to_csv(cls, test_suite: TestSuite) -> str:
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Header
        writer.writerow([
            "Test ID", "Title", "Category", "Priority",
            "User Story ID", "AC ID", "Pre-conditions",
            "Test Steps", "Expected Result", "Status"
        ])

        for tc in test_suite.test_cases:
            writer.writerow([
                tc.id,
                tc.title,
                tc.category,
                tc.priority,
                tc.user_story_id or "",
                tc.acceptance_criteria_id or "",
                " | ".join(tc.pre_conditions),
                " | ".join(tc.test_steps),
                tc.expected_result,
                tc.status
            ])

        return output.getvalue()

    @classmethod
    def to_excel_bytes(cls, test_suite: TestSuite) -> bytes:
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Test Cases"

        # Theme Colors
        navy_header_fill = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")
        header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        regular_font = Font(name="Calibri", size=10)
        bold_font = Font(name="Calibri", size=10, bold=True)
        thin_border = Border(
            left=Side(style='thin', color='CBD5E1'),
            right=Side(style='thin', color='CBD5E1'),
            top=Side(style='thin', color='CBD5E1'),
            bottom=Side(style='thin', color='CBD5E1')
        )

        headers = [
            "Test ID", "Title", "Category", "Priority",
            "User Story ID", "AC ID", "Pre-conditions",
            "Test Steps", "Expected Result", "Status"
        ]
        ws.append(headers)

        for col_num in range(1, len(headers) + 1):
            cell = ws.cell(row=1, column=col_num)
            cell.fill = navy_header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

        # Alternating row fill
        alt_fill = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")

        for r_idx, tc in enumerate(test_suite.test_cases, start=2):
            row_data = [
                tc.id,
                tc.title,
                tc.category,
                tc.priority,
                tc.user_story_id or "",
                tc.acceptance_criteria_id or "",
                "\n".join(tc.pre_conditions),
                "\n".join(tc.test_steps),
                tc.expected_result,
                tc.status
            ]
            ws.append(row_data)

            for col_idx in range(1, len(row_data) + 1):
                cell = ws.cell(row=r_idx, column=col_idx)
                cell.font = regular_font
                cell.border = thin_border
                cell.alignment = Alignment(vertical="top", wrap_text=True)
                if r_idx % 2 == 1:
                    cell.fill = alt_fill

        # Adjust column widths
        col_widths = {
            1: 12,  # Test ID
            2: 30,  # Title
            3: 20,  # Category
            4: 12,  # Priority
            5: 14,  # User Story ID
            6: 12,  # AC ID
            7: 25,  # Pre-conditions
            8: 35,  # Test Steps
            9: 35,  # Expected Result
            10: 10  # Status
        }
        for col_idx, width in col_widths.items():
            ws.column_dimensions[openpyxl.utils.get_column_letter(col_idx)].width = width

        buffer = io.BytesIO()
        wb.save(buffer)
        buffer.seek(0)
        return buffer.getvalue()
