# Order Error Log

Three tabs:
1. **Log an error** (team passcode): order ID -> packer / assembler / packing time fill in from Samasya; pick Internal / External / Unknown, the specific reason, drugs affected, description.
2. **Analytics** (admin passcode): error % and accuracy % per packer and assembler for any date range (by packing date), by month, by reason.
3. **Logs** (admin passcode): read-only list with date filter (reported or packed), search and type filter. Open one entry to see everything, and reverse it if an appeal is accepted (the row stays, its points stop counting). Entries cannot be edited.

## Rules (edit in config.py)
- Internal (camera checked, our mistake): 1 point per wrong drug to the packer AND the assembler.
- Wrong label / non-English address not held back: 2 points to the packer (once per order).
- "Assembly error caught by packer at packing": 1 point per wrong drug to the assembler only.
- External (our packing was fine) and Unknown (could not verify): no points.
- Error % = points / orders handled x 100 for orders packed in the chosen dates. Accuracy % = 100 - error %.
- The same mistake on the same order counts once; a different mistake on the same order is a new entry.

## Run locally
    pip install -r requirements.txt
    cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # fill in
    streamlit run app.py
    python -m pytest tests

## Deploy (Streamlit Community Cloud)
1. Push to a private GitHub repo (secrets.toml and *.json are git-ignored - keep it that way).
2. share.streamlit.io > Create app > repo, main file `app.py`.
3. App settings > Secrets > paste the filled-in secrets.toml (the [ssh] and [db] blocks are the same as the efficiency dashboard's).
4. Share the link + team passcode with the executives. Tabs 2 and 3 need the admin passcode.

## Load the old data once (2026 only)
    python clean_history.py error_of_order.xlsx past_orders_extracted.csv history_cleaned.csv
Google Sheet > `errors` tab (created on first run) > File > Import > Upload > "Replace current sheet" (untick "convert text to numbers, dates and formulas").
Filter the `needs_review` column and fix flagged rows by hand.

## Files
- app.py - the three tabs          - analysis.py - error % / search numbers (pure pandas)
- db.py - Samasya lookup + daily order counts   - sheets.py - Google Sheets read/write
- config.py - columns, reasons, points rules, names (LOGIN_NAMES), START_DATE
