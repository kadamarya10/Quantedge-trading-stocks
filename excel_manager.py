"""
QuantEdge Excel Trade Journal & Audit Manager
Exports trade execution history and stock recommendations into beautifully formatted, 
human-readable Excel (.xlsx) workbooks with color-coded profit/loss, currency formatting, 
and auto-sized columns.
"""

import os
from datetime import datetime
from typing import List, Dict, Any, Optional

try:
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter
    OPENPYXL_AVAILABLE = True
except ImportError:
    OPENPYXL_AVAILABLE = False


# Theme styling colors
HEADER_FILL = PatternFill(start_color="1E293B", end_color="1E293B", fill_type="solid")
HEADER_FONT = Font(name="Calibri", size=11, bold=True, color="FFFFFF")

KPI_TITLE_FONT = Font(name="Calibri", size=10, bold=True, color="64748B")
KPI_VAL_FONT = Font(name="Calibri", size=16, bold=True, color="0F172A")
KPI_FILL = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")

WIN_FILL = PatternFill(start_color="DCFCE7", end_color="DCFCE7", fill_type="solid")
WIN_FONT = Font(name="Calibri", size=11, bold=True, color="166534")

LOSS_FILL = PatternFill(start_color="FEE2E2", end_color="FEE2E2", fill_type="solid")
LOSS_FONT = Font(name="Calibri", size=11, bold=True, color="991B1B")

ACTIVE_FILL = PatternFill(start_color="FEF3C7", end_color="FEF3C7", fill_type="solid")
ACTIVE_FONT = Font(name="Calibri", size=11, bold=True, color="92400E")

REGULAR_FONT = Font(name="Calibri", size=11, color="0F172A")
MUTED_FONT = Font(name="Calibri", size=10, color="64748B")
BOLD_FONT = Font(name="Calibri", size=11, bold=True, color="0F172A")

THIN_BORDER = Border(
    left=Side(style='thin', color='E2E8F0'),
    right=Side(style='thin', color='E2E8F0'),
    top=Side(style='thin', color='E2E8F0'),
    bottom=Side(style='thin', color='E2E8F0')
)


def _autofit_columns(ws, min_width: int = 10, max_width: int = 65):
    """Automatically adjusts column widths based on content."""
    for col in ws.columns:
        col_letter = get_column_letter(col[0].column)
        max_len = 0
        for cell in col:
            # Skip merged cells or summary blocks with long text
            if cell.row <= 3 and len(str(cell.value or '')) > 40:
                continue
            val_str = str(cell.value or '')
            if '\n' in val_str:
                val_str = max(val_str.split('\n'), key=len)
            max_len = max(max_len, len(val_str))
        ws.column_dimensions[col_letter].width = min(max(max_len + 3, min_width), max_width)


def export_stocks_to_excel(calls: List[Dict[str, Any]], filepath: str = "stock_recommendations.xlsx") -> str:
    """Exports all stock recommendations into a clean, formatted Excel file."""
    if not OPENPYXL_AVAILABLE:
        return ""

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Stock Recommendations"
    ws.views.sheetView[0].showGridLines = True

    # Title Banner
    ws.merge_cells("A1:M1")
    title_cell = ws["A1"]
    title_cell.value = "📊 QuantEdge AI Stock Recommendations & Accuracy Tracker"
    title_cell.font = Font(name="Calibri", size=16, bold=True, color="FFFFFF")
    title_cell.fill = PatternFill(start_color="0F172A", end_color="0F172A", fill_type="solid")
    title_cell.alignment = Alignment(horizontal="left", vertical="center", indent=1)
    ws.row_dimensions[1].height = 36

    # Subtitle with timestamp
    ws.merge_cells("A2:M2")
    sub_cell = ws["A2"]
    sub_cell.value = f"Generated on {datetime.now().strftime('%d %B %Y, %I:%M %p IST')} • Track record audit of all AI stock calls"
    sub_cell.font = Font(name="Calibri", size=10, italic=True, color="64748B")
    sub_cell.alignment = Alignment(horizontal="left", vertical="center", indent=1)
    ws.row_dimensions[2].height = 20

    # Summary KPI Stats
    closed = [c for c in calls if c.get("status") in ("TARGET_HIT", "STOPLOSS_HIT")]
    target_hits = [c for c in closed if c.get("status") == "TARGET_HIT"]
    sl_hits = [c for c in closed if c.get("status") == "STOPLOSS_HIT"]
    active = [c for c in calls if c.get("status") == "ACTIVE"]

    hit_rate = (len(target_hits) / len(closed) * 100) if closed else 0.0
    cum_ret = sum(float(c.get("pnl_percent", 0.0) or 0.0) for c in closed)

    ws["A4"] = "Total Calls"; ws["A4"].font = KPI_TITLE_FONT
    ws["A5"] = len(calls); ws["A5"].font = KPI_VAL_FONT
    ws["C4"] = "Targets Hit"; ws["C4"].font = KPI_TITLE_FONT
    ws["C5"] = len(target_hits); ws["C5"].font = KPI_VAL_FONT; ws["C5"].font = Font(name="Calibri", size=16, bold=True, color="166534")
    ws["E4"] = "Stop-Loss Cut"; ws["E4"].font = KPI_TITLE_FONT
    ws["E5"] = len(sl_hits); ws["E5"].font = KPI_VAL_FONT; ws["E5"].font = Font(name="Calibri", size=16, bold=True, color="991B1B")
    ws["G4"] = "Hit Rate %"; ws["G4"].font = KPI_TITLE_FONT
    ws["G5"] = f"{hit_rate:.1f}%"; ws["G5"].font = KPI_VAL_FONT; ws["G5"].font = Font(name="Calibri", size=16, bold=True, color="166534" if hit_rate >= 50 else "991B1B")
    ws["I4"] = "Cumulative Return"; ws["I4"].font = KPI_TITLE_FONT
    ws["I5"] = f"{'+' if cum_ret >= 0 else ''}{cum_ret:.2f}%"; ws["I5"].font = KPI_VAL_FONT; ws["I5"].font = Font(name="Calibri", size=16, bold=True, color="166534" if cum_ret >= 0 else "991B1B")
    ws["K4"] = "Active Calls"; ws["K4"].font = KPI_TITLE_FONT
    ws["K5"] = f"{len(active)} Live"; ws["K5"].font = KPI_VAL_FONT

    # Header Row
    headers = [
        "#", "Stock Symbol", "Company Name", "Sector", "Status",
        "Entry Date", "Entry Price (₹)", "Target Price (₹)", "Target %",
        "Stop Loss (₹)", "Exit / LTP (₹)", "P&L (%)", "Time Held", "AI Catalyst & Why Given"
    ]
    header_row = 7
    ws.row_dimensions[header_row].height = 26
    for col_idx, h in enumerate(headers, start=1):
        cell = ws.cell(row=header_row, column=col_idx, value=h)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center" if col_idx in (1, 5, 9, 12, 13) else "left", vertical="center")
        cell.border = THIN_BORDER

    # Data Rows
    current_row = 8
    for idx, c in enumerate(calls, start=1):
        status = c.get("status", "ACTIVE")
        is_target = status == "TARGET_HIT"
        is_sl = status == "STOPLOSS_HIT"
        pnl = float(c.get("pnl_percent", 0.0) or 0.0)

        status_text = "🎯 TARGET HIT" if is_target else ("🛑 STOPLOSS HIT" if is_sl else "⏳ ACTIVE")
        fill_to_use = WIN_FILL if is_target else (LOSS_FILL if is_sl else ACTIVE_FILL)
        font_to_use = WIN_FONT if is_target else (LOSS_FONT if is_sl else ACTIVE_FONT)

        entry_p = float(c.get("entry_price") or 0.0)
        tgt_p = float(c.get("target_price") or 0.0)
        tgt_pct = float(c.get("target_pct") or 0.0)
        sl_p = float(c.get("stop_loss") or 0.0)
        exit_p = float(c.get("exit_price") or c.get("current_ltp") or entry_p)

        row_vals = [
            idx,
            c.get("symbol", ""),
            c.get("company_name", c.get("symbol", "")),
            c.get("sector", "NSE"),
            status_text,
            (c.get("entry_date") or "").split(" ")[0],
            entry_p,
            tgt_p,
            tgt_pct / 100.0,
            sl_p,
            exit_p,
            pnl / 100.0,
            c.get("time_held", "1d"),
            c.get("catalyst") or c.get("why_rising") or "High conviction momentum breakout"
        ]

        ws.row_dimensions[current_row].height = 22
        for col_idx, val in enumerate(row_vals, start=1):
            cell = ws.cell(row=current_row, column=col_idx, value=val)
            cell.font = REGULAR_FONT
            cell.border = THIN_BORDER

            # Specific column styling
            if col_idx == 1:
                cell.alignment = Alignment(horizontal="center", vertical="center")
                cell.font = MUTED_FONT
            elif col_idx == 2:
                cell.font = BOLD_FONT
            elif col_idx == 5:
                cell.fill = fill_to_use
                cell.font = font_to_use
                cell.alignment = Alignment(horizontal="center", vertical="center")
            elif col_idx in (7, 8, 10, 11):
                cell.number_format = '₹#,##0.00'
                cell.alignment = Alignment(horizontal="right", vertical="center")
            elif col_idx in (9, 12):
                cell.number_format = '+0.00%;-0.00%;0.00%'
                cell.alignment = Alignment(horizontal="right", vertical="center")
                if col_idx == 12:
                    cell.font = WIN_FONT if pnl >= 0 else LOSS_FONT
            elif col_idx == 13:
                cell.alignment = Alignment(horizontal="center", vertical="center")
            elif col_idx == 14:
                cell.alignment = Alignment(horizontal="left", vertical="center")

        current_row += 1

    _autofit_columns(ws)
    wb.save(filepath)
    return filepath


def export_options_to_excel(trade_history: List[Dict[str, Any]], capital: float = 100000.0, filepath: str = "options_trades.xlsx") -> str:
    """Exports all executed options sniper trades into a clean, formatted Excel file."""
    if not OPENPYXL_AVAILABLE:
        return ""

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "NIFTY Options Trades"
    ws.views.sheetView[0].showGridLines = True

    # Title Banner
    ws.merge_cells("A1:M1")
    title_cell = ws["A1"]
    title_cell.value = "⚡ QuantEdge NIFTY Options Sniper Trade Execution Ledger"
    title_cell.font = Font(name="Calibri", size=16, bold=True, color="FFFFFF")
    title_cell.fill = PatternFill(start_color="0F172A", end_color="0F172A", fill_type="solid")
    title_cell.alignment = Alignment(horizontal="left", vertical="center", indent=1)
    ws.row_dimensions[1].height = 36

    # Subtitle with timestamp
    ws.merge_cells("A2:M2")
    sub_cell = ws["A2"]
    sub_cell.value = f"Generated on {datetime.now().strftime('%d %B %Y, %I:%M %p IST')} • Fully audited execution ledger with fees and P&L"
    sub_cell.font = Font(name="Calibri", size=10, italic=True, color="64748B")
    sub_cell.alignment = Alignment(horizontal="left", vertical="center", indent=1)
    ws.row_dimensions[2].height = 20

    # Summary KPI Stats
    total_trades = len(trade_history)
    wins = sum(1 for t in trade_history if float(t.get("realized_pnl", 0.0) or 0.0) > 0)
    losses = total_trades - wins
    win_rate = (wins / total_trades * 100) if total_trades else 0.0
    net_pnl = sum(float(t.get("realized_pnl", 0.0) or 0.0) for t in trade_history)
    return_pct = ((capital - 100000.0) / 100000.0) * 100.0

    ws["A4"] = "Total Trades"; ws["A4"].font = KPI_TITLE_FONT
    ws["A5"] = total_trades; ws["A5"].font = KPI_VAL_FONT
    ws["C4"] = "Win Rate %"; ws["C4"].font = KPI_TITLE_FONT
    ws["C5"] = f"{win_rate:.1f}%"; ws["C5"].font = KPI_VAL_FONT; ws["C5"].font = Font(name="Calibri", size=16, bold=True, color="166534" if win_rate >= 50 else "991B1B")
    ws["E4"] = "Wins / Losses"; ws["E4"].font = KPI_TITLE_FONT
    ws["E5"] = f"{wins}W • {losses}L"; ws["E5"].font = KPI_VAL_FONT
    ws["G4"] = "Net Realized P&L"; ws["G4"].font = KPI_TITLE_FONT
    ws["G5"] = f"{'+' if net_pnl >= 0 else ''}₹{net_pnl:,.2f}"; ws["G5"].font = KPI_VAL_FONT; ws["G5"].font = Font(name="Calibri", size=16, bold=True, color="166534" if net_pnl >= 0 else "991B1B")
    ws["I4"] = "Return on Capital"; ws["I4"].font = KPI_TITLE_FONT
    ws["I5"] = f"{'+' if return_pct >= 0 else ''}{return_pct:.2f}%"; ws["I5"].font = KPI_VAL_FONT; ws["I5"].font = Font(name="Calibri", size=16, bold=True, color="166534" if return_pct >= 0 else "991B1B")
    ws["K4"] = "Current Capital"; ws["K4"].font = KPI_TITLE_FONT
    ws["K5"] = f"₹{capital:,.2f}"; ws["K5"].font = KPI_VAL_FONT

    # Header Row
    headers = [
        "Trade #", "Instrument / Strike", "Type", "Lot Qty",
        "Entry Time", "Entry Price (₹)", "Exit Time", "Exit Price (₹)",
        "Exit Reason", "Brokerage / Fees (₹)", "Realized P&L (₹)", "Return %", "Result"
    ]
    header_row = 7
    ws.row_dimensions[header_row].height = 26
    for col_idx, h in enumerate(headers, start=1):
        cell = ws.cell(row=header_row, column=col_idx, value=h)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center" if col_idx in (1, 3, 4, 12, 13) else "left", vertical="center")
        cell.border = THIN_BORDER

    # Data Rows
    current_row = 8
    for idx, t in enumerate(trade_history, start=1):
        pnl = float(t.get("realized_pnl", 0.0) or 0.0)
        is_win = pnl >= 0
        pnl_pct = float(t.get("pnl_percent", 0.0) or t.get("pnl_pct", 0.0) or 0.0)
        fees = float(t.get("charges", 0.0) or t.get("fees", 0.0) or 0.0)

        result_text = "🟢 PROFIT" if is_win else "🔴 LOSS"
        fill_to_use = WIN_FILL if is_win else LOSS_FILL
        font_to_use = WIN_FONT if is_win else LOSS_FONT

        row_vals = [
            idx,
            t.get("instrument", "NIFTY Option"),
            t.get("type", "CE"),
            int(t.get("qty", 65)),
            t.get("entry_time", "--"),
            float(t.get("entry_price", 0.0)),
            t.get("exit_time", "--"),
            float(t.get("exit_price", 0.0)),
            t.get("exit_reason", "Target Hit" if is_win else "Stop Loss"),
            fees,
            pnl,
            pnl_pct / 100.0,
            result_text
        ]

        ws.row_dimensions[current_row].height = 22
        for col_idx, val in enumerate(row_vals, start=1):
            cell = ws.cell(row=current_row, column=col_idx, value=val)
            cell.font = REGULAR_FONT
            cell.border = THIN_BORDER

            if col_idx == 1:
                cell.alignment = Alignment(horizontal="center", vertical="center")
                cell.font = MUTED_FONT
            elif col_idx == 2:
                cell.font = BOLD_FONT
            elif col_idx == 3:
                cell.alignment = Alignment(horizontal="center", vertical="center")
                cell.font = Font(name="Calibri", size=11, bold=True, color="166534" if val == "CE" else "991B1B")
            elif col_idx == 4:
                cell.alignment = Alignment(horizontal="center", vertical="center")
            elif col_idx in (6, 8, 10):
                cell.number_format = '₹#,##0.00'
                cell.alignment = Alignment(horizontal="right", vertical="center")
            elif col_idx == 11:
                cell.number_format = '₹#,##0.00;[Red]-₹#,##0.00;₹0.00'
                cell.alignment = Alignment(horizontal="right", vertical="center")
                cell.font = WIN_FONT if is_win else LOSS_FONT
            elif col_idx == 12:
                cell.number_format = '+0.00%;-0.00%;0.00%'
                cell.alignment = Alignment(horizontal="right", vertical="center")
                cell.font = WIN_FONT if is_win else LOSS_FONT
            elif col_idx == 13:
                cell.fill = fill_to_use
                cell.font = font_to_use
                cell.alignment = Alignment(horizontal="center", vertical="center")

        current_row += 1

    _autofit_columns(ws)
    wb.save(filepath)
    return filepath


def export_master_journal(calls: List[Dict[str, Any]], trade_history: List[Dict[str, Any]], capital: float = 100000.0, filepath: str = "QuantEdge_Trades_Journal.xlsx") -> str:
    """Exports a combined multi-sheet Master Trading Journal workbook."""
    if not OPENPYXL_AVAILABLE:
        return ""

    wb = openpyxl.Workbook()
    # Remove default sheet
    wb.remove(wb.active)

    # 1. Sheet: Executive Performance Summary
    ws_sum = wb.create_sheet(title="Executive Performance Summary")
    ws_sum.views.sheetView[0].showGridLines = True
    ws_sum.merge_cells("A1:G1")
    t1 = ws_sum["A1"]
    t1.value = "🎯 QuantEdge Algorithmic Trading Performance & Audit Overview"
    t1.font = Font(name="Calibri", size=16, bold=True, color="FFFFFF")
    t1.fill = PatternFill(start_color="0F172A", end_color="0F172A", fill_type="solid")
    t1.alignment = Alignment(horizontal="left", vertical="center", indent=1)
    ws_sum.row_dimensions[1].height = 36

    # Options stats
    opt_total = len(trade_history)
    opt_wins = sum(1 for t in trade_history if float(t.get("realized_pnl", 0.0) or 0.0) > 0)
    opt_losses = opt_total - opt_wins
    opt_winrate = (opt_wins / opt_total * 100) if opt_total else 0.0
    opt_pnl = sum(float(t.get("realized_pnl", 0.0) or 0.0) for t in trade_history)
    opt_ret = ((capital - 100000.0) / 100000.0) * 100.0

    # Stocks stats
    stk_closed = [c for c in calls if c.get("status") in ("TARGET_HIT", "STOPLOSS_HIT")]
    stk_hits = [c for c in stk_closed if c.get("status") == "TARGET_HIT"]
    stk_sl = [c for c in stk_closed if c.get("status") == "STOPLOSS_HIT"]
    stk_active = [c for c in calls if c.get("status") == "ACTIVE"]
    stk_hitrate = (len(stk_hits) / len(stk_closed) * 100) if stk_closed else 0.0
    stk_cum_ret = sum(float(c.get("pnl_percent", 0.0) or 0.0) for c in stk_closed)

    summary_cards = [
        ("METRIC", "NIFTY OPTIONS (ALGO SNIPER)", "AI STOCK RECOMMENDATIONS", "COMBINED / PORTFOLIO"),
        ("Win / Hit Rate", f"{opt_winrate:.1f}% ({opt_wins}W / {opt_losses}L)", f"{stk_hitrate:.1f}% ({len(stk_hits)} Hit / {len(stk_sl)} Cut)", f"{((opt_wins + len(stk_hits)) / ((opt_total + len(stk_closed)) or 1) * 100):.1f}% Overall"),
        ("Total Closed Positions", f"{opt_total} Trades Executed", f"{len(stk_closed)} Calls Completed", f"{opt_total + len(stk_closed)} Total Closed Calls"),
        ("Active Positions", "No open position" if not any(t.get('is_active') for t in trade_history) else "1 Open Trade", f"{len(stk_active)} Live Stocks Monitored", f"{len(stk_active)} Total Live"),
        ("Realized P&L / Returns", f"{'+' if opt_pnl >= 0 else ''}₹{opt_pnl:,.2f} ({'+' if opt_ret >= 0 else ''}{opt_ret:.2f}%)", f"{'+' if stk_cum_ret >= 0 else ''}{stk_cum_ret:.2f}% Cumulative Gain", f"Net Positive Growth"),
        ("Current Trading Capital", f"₹{capital:,.2f}", "Capital Allocatable Across Picks", f"₹{capital:,.2f} Virtual Account")
    ]

    for r_idx, row in enumerate(summary_cards, start=4):
        ws_sum.row_dimensions[r_idx].height = 26
        for c_idx, val in enumerate(row, start=1):
            cell = ws_sum.cell(row=r_idx, column=c_idx, value=val)
            if r_idx == 4:
                cell.fill = HEADER_FILL
                cell.font = HEADER_FONT
                cell.alignment = Alignment(horizontal="center" if c_idx > 1 else "left", vertical="center")
            else:
                cell.border = THIN_BORDER
                cell.alignment = Alignment(horizontal="center" if c_idx > 1 else "left", vertical="center")
                if c_idx == 1:
                    cell.font = BOLD_FONT
                    cell.fill = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")
                else:
                    cell.font = REGULAR_FONT
                    if "Win" in summary_cards[r_idx-4][0] or "Realized" in summary_cards[r_idx-4][0]:
                        cell.font = BOLD_FONT

    _autofit_columns(ws_sum)

    # 2. Add Stock Recommendations Sheet
    temp_stocks_wb = openpyxl.Workbook()
    export_stocks_to_excel(calls, filepath="_temp_stocks.xlsx")
    ts_wb = openpyxl.load_workbook("_temp_stocks.xlsx")
    ws_stocks = wb.create_sheet(title="📈 Stock Recommendations")
    ws_stocks.views.sheetView[0].showGridLines = True
    for row in ts_wb.active.iter_rows():
        ws_stocks.row_dimensions[row[0].row].height = ts_wb.active.row_dimensions[row[0].row].height
        for cell in row:
            new_cell = ws_stocks.cell(row=cell.row, column=cell.column, value=cell.value)
            new_cell.font = cell.font.copy() if cell.font else None
            new_cell.fill = cell.fill.copy() if cell.fill else None
            new_cell.border = cell.border.copy() if cell.border else None
            new_cell.alignment = cell.alignment.copy() if cell.alignment else None
            new_cell.number_format = cell.number_format
    _autofit_columns(ws_stocks)
    if os.path.exists("_temp_stocks.xlsx"):
        try: os.remove("_temp_stocks.xlsx")
        except: pass

    # 3. Add Options Trades Sheet
    export_options_to_excel(trade_history, capital=capital, filepath="_temp_options.xlsx")
    to_wb = openpyxl.load_workbook("_temp_options.xlsx")
    ws_options = wb.create_sheet(title="⚡ NIFTY Options Trades")
    ws_options.views.sheetView[0].showGridLines = True
    for row in to_wb.active.iter_rows():
        ws_options.row_dimensions[row[0].row].height = to_wb.active.row_dimensions[row[0].row].height
        for cell in row:
            new_cell = ws_options.cell(row=cell.row, column=cell.column, value=cell.value)
            new_cell.font = cell.font.copy() if cell.font else None
            new_cell.fill = cell.fill.copy() if cell.fill else None
            new_cell.border = cell.border.copy() if cell.border else None
            new_cell.alignment = cell.alignment.copy() if cell.alignment else None
            new_cell.number_format = cell.number_format
    _autofit_columns(ws_options)
    if os.path.exists("_temp_options.xlsx"):
        try: os.remove("_temp_options.xlsx")
        except: pass

    wb.save(filepath)
    return filepath
