# Snag+

**Live:** https://elitanz.github.io/snag-plus/

An upgraded Snag, the thrift-flip checker. Snap a find, and it tells you what the item sells for, what you'd make after fees, shipping and tax, and whether to buy it (BUY / MAYBE / SKIP). It also writes a ready-to-post listing.

## What's new compared to the original Snag
- **A new look built from real thrift-store objects:** newsprint paper, a fluorescent yard-sale sticker, the result as a manila hang tag, the verdict slammed down as a rubber stamp, and a register receipt.
- **Price-tag ruler.** One bar shows the buy zone, the thin-margin zone and the losing zone, with a pin at the price on the tag, so you get the answer at a glance in the aisle.
- **Today's haul.** Add finds to a cart while you shop. It shows what you'll spend against a trip budget plus the expected profit, and "I bought these" moves them all to Bought.
- **Color-tag sales.** Set this week's sale color (say, blue tags 50% off), tap the tag color when you scan, and the discount comes off automatically.
- **Profit by week** for the last 8 weeks, plus a monthly profit goal.
- **Reads barcodes, UPCs and ISBNs** in your photos to pin down the exact product.
- **Reads the price sticker.** Leave the price blank and Snag reads it from your photo.
- **"Not right? Correct it."** Tell Snag what the item really is and it re-prices it using the same photos.
- **Fees checked against each platform (November 2026):** eBay 13.6% + $0.40 ($0.30 on orders of $10 or less), Poshmark 20% or $2.95 under $15, Mercari 10%, Depop 3.3% + $0.45, Etsy 6.5% + 3% + $0.25 + $0.20 listing, Grailed 6% under $120 / 9% from $120 + 3.49% + $0.49, Discogs 9% + PayPal processing.
- **New logo:** a fishhook that's snagged a price tag.
- **Sales tax setting.** Profit, ROI and "max to pay" include the tax you pay at the register.
- **Clear BUY rule.** The receipt shows exactly how much profit a BUY needs.
- **Works anywhere, nothing to install:** AI checks run in the cloud (free Cloudflare Worker), including on your phone in the store.
- **Homepage explains how it works** instead of showing a made-up example item.
- **Left column scrolls on its own** on desktop, so the scan form is always reachable.
- **Five price-check links** instead of one: eBay sold and Poshmark sold (what items actually sold for), plus Mercari, Etsy and Google Shopping (current asking prices).
- **Shelf-age alerts.** Listed 30+ days suggests a price drop; bought and not listed for a week gets flagged.
- **My finds tools:** search, sort by profit or age, undo delete, and copy everything to Google Sheets or Excel.
- **Stats:** average days to sell.
- Drag-and-drop or paste photos on desktop, pick several photos at once, ⌘/Ctrl+Enter to check, and a buzz on BUY (Android phones; iPhones don't allow it).

## How the AI checks work (free, nothing to run)

The page calls **Snag AI**, a small Cloudflare Worker (`worker/`) at `https://snag-ai.snag-ai.workers.dev`. It only answers requests from elitanz.github.io (and localhost for testing).

- **Photo checks:** Google Gemini's fast "lite" models first (best prices), then Cloudflare's own free vision model (Llama 4 Scout) once Gemini's free daily quota is used up, then Gemini's bigger models.
- **"Ask about this item":** Groq first (fast, about 1,000 free questions a day), then the models above.
- **Keys** (Gemini, Groq) are encrypted Worker secrets on Cloudflare. They are never in this repo or sent to the browser.
- Free-tier answers are rougher than paid ones, so check the eBay sold link before spending big.

To update the Worker after editing `worker/src/index.js`: `cd worker && npx wrangler deploy`.

On claude.ai (as an artifact), Claude does the checks instead. `serve.py` is an optional way to run everything on a computer without the Worker.

Single-file static page (`index.html`), no build step.
