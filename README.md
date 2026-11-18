# Snag+

**Live:** https://elitanz.github.io/snag-plus/

An upgraded Snag, the thrift-flip checker. Snap a find, and it tells you what the item sells for, what you'd make after fees, shipping and tax, and whether to buy it (BUY / MAYBE / SKIP). It also writes a ready-to-post listing.

## What's new compared to the original Snag
- **Reads the price sticker.** Leave the price blank and Snag reads it from your photo.
- **"Not right? Correct it."** Tell Snag what the item really is and it re-prices it using the same photos.
- **Fees checked against each platform (November 2026):** eBay 13.6% + $0.40 ($0.30 on orders of $10 or less), Poshmark 20% or $2.95 under $15, Mercari 10%, Depop 3.3% + $0.45, Etsy 6.5% + 3% + $0.25 + $0.20 listing, Grailed 6% under $120 / 9% from $120 + 3.49% + $0.49, Discogs 9% + PayPal processing.
- **New logo:** a fishhook that's snagged a price tag.
- **Sales tax setting.** Profit, ROI and "max to pay" include the tax you pay at the register.
- **Clear BUY rule.** The receipt shows exactly how much profit a BUY needs.
- **Five price-check links** instead of one: eBay sold and Poshmark sold (what items actually sold for), plus Mercari, Etsy and Google Shopping (current asking prices).
- **Shelf-age alerts.** Listed 30+ days suggests a price drop; bought and not listed for a week gets flagged.
- **My finds tools:** search, sort by profit or age, undo delete, and copy everything to Google Sheets or Excel.
- **Stats:** average days to sell.
- Drag-and-drop or paste photos on desktop, pick several photos at once, ⌘/Ctrl+Enter to check, and a buzz on BUY (Android phones; iPhones don't allow it).

Note: the AI checks only run when Snag is opened as an artifact on claude.ai. This GitHub Pages copy shows the interactive example, and finds save in your browser.

Single-file static page (`index.html`), no build step.
