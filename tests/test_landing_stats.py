from mahogany.jobs.update_landing import _fmt_price, update_stats


def test_fmt_price():
    assert _fmt_price(685_000) == "$685k"
    assert _fmt_price(1_250_000) == "$1.25M"


def test_update_stats_patches_data_stat():
    html = """
    <strong id="stat-active" data-stat="active">0</strong>
    <strong id="stat-median" data-stat="median">$0</strong>
    <strong id="stat-entry" data-stat="entry">$0</strong>
    <strong id="stat-gas" data-stat="gas">0¢</strong>
    <strong id="mkt-new" data-stat="new-week">0</strong>
    Updated never
    """
    listings = [
        {"price": 500_000, "days_on_market": 2},
        {"price": 700_000, "days_on_market": 10},
        {"price": 600_000, "days_on_market": 1},
    ]
    out = update_stats(html, listings, {"calgary": 159.4})
    assert 'data-stat="active">3<' in out
    assert 'data-stat="median">$600k<' in out
    assert 'data-stat="entry">$500k<' in out
    assert 'data-stat="new-week">2<' in out
    assert 'data-stat="gas">159¢<' in out
