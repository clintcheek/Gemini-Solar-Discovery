from solar_discovery.parser import parse_results

HTML = """
<html><body>
<table>
<thead><tr>
<th>Grantor</th><th>Grantee</th><th>Doc Type</th><th>Recorded Date</th>
<th>Doc Number</th><th>Book/Volume/Page</th><th>Town</th><th>Legal Description</th>
</tr></thead>
<tbody><tr>
<td>SMITH JOHN</td><td>GOODLEAP LLC</td><td>UCC FINANCING STATEMENT</td><td>07/10/2026</td>
<td><a href="/Document/20260012345">20260012345</a></td><td>2026/100/5</td><td>DALLAS</td>
<td>LOT 4 BLOCK A; 123 MAIN ST DALLAS TX 75201</td>
</tr></tbody>
</table>
</body></html>
"""


def test_structured_table_parser():
    records = parse_results(HTML, "GoodLeap", "https://dallas.tx.publicsearch.us/")
    assert len(records) == 1
    record = records[0]
    assert record.borrower == "SMITH JOHN"
    assert record.lender == "GOODLEAP LLC"
    assert record.document_number == "20260012345"
    assert record.loan_date == "07/10/2026"
    assert record.county == "Dallas"
    assert record.status == "Active"
    assert "123 MAIN ST" in record.property_address
    assert record.source_url == "https://dallas.tx.publicsearch.us/Document/20260012345"

CARD_HTML = """
<html><body>
<div class="result-card">
  Grantor: JONES MARY
  Grantee: MOSAIC SOLAR LLC
  Document Type: UCC FINANCING STATEMENT
  Recorded Date: 07/11/2026
  Document Number: <a href="/Document/20260054321">20260054321</a>
  Town: DALLAS
  Legal Description: LOT 9 BLOCK B 456 OAK DR DALLAS TX 75202
</div>
</body></html>
"""


def test_labeled_card_parser():
    records = parse_results(CARD_HTML, "Mosaic", "https://dallas.tx.publicsearch.us/")
    assert len(records) == 1
    record = records[0]
    assert record.borrower == "JONES MARY"
    assert record.lender == "MOSAIC SOLAR LLC"
    assert record.document_number == "20260054321"
    assert "456 OAK DR" in record.property_address
