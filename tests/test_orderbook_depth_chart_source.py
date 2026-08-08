from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GUI = ROOT / "bot_gui.html"
BOT_LOOP = ROOT / "src" / "catalyst" / "bot_loop.py"


def test_orderbook_depth_chart_uses_independent_side_price_lanes():
    html = GUI.read_text(encoding="utf-8")

    assert "const sideLaneGap" in html
    assert "const buySpan = priceSpan(buyLow, buyHigh)" in html
    assert "if (!buySpan) return buyLaneRight" in html
    assert "const sellSpan = priceSpan(sellLow, sellHigh)" in html
    assert "if (!sellSpan) return sellLaneLeft" in html
    assert "function xAtBuy(price)" in html
    assert "function xAtSell(price)" in html
    assert "drawStep(buyCum, buyFill, buyLine, xAtBuy)" in html
    assert "drawStep(sellCum, sellFill, sellLine, xAtSell)" in html
    assert "ctx.fillText(buyLow.toFixed(6), padL, h - padB + 8)" in html
    assert "ctx.fillText(sellHigh.toFixed(6), w - padR, h - padB + 8)" in html


def test_market_intel_slippage_uses_one_xch_default_trade():
    html = GUI.read_text(encoding="utf-8")

    assert "/api/market/slippage?amount=1&side=buy" in html
    assert "A 1 XCH test trade is " in html
    assert "For a 1 XCH test trade" in html
    assert "/api/market/slippage?amount=0.01&side=buy" not in html


def test_market_intel_shows_crossed_public_book_instead_of_blank_spread():
    html = GUI.read_text(encoding="utf-8")

    assert "bestBid > 0 && bestAsk > 0 && bestBid >= bestAsk" in html
    assert "Crossed" in html


def test_market_intel_depth_card_prefers_dexie_totals_for_display():
    html = GUI.read_text(encoding="utf-8")

    assert "data.dexie_total_buy_depth_xch ?? data.buy_depth_xch" in html
    assert "data.dexie_total_sell_depth_cat" in html
    assert "marketIntelCatTicker()" in html
    assert "data.buy_depth_xch ?? displayBuyDepth" in html
    assert "data.sell_depth_xch ?? displaySellDepthXch" in html


def test_market_intel_sse_payload_includes_dexie_totals():
    bot_loop = BOT_LOOP.read_text(encoding="utf-8")

    assert '"dexie_total_buy_depth_xch"' in bot_loop
    assert '"dexie_total_buy_depth_cat"' in bot_loop
    assert '"dexie_total_sell_depth_xch"' in bot_loop
    assert '"dexie_total_sell_depth_cat"' in bot_loop
