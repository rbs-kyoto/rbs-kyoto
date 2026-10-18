_FULLWIDTH_DIGITS = str.maketrans("0123456789", "０１２３４５６７８９")


def format_fiscal_year(year):
    eras = (
        (2019, "令和", 2018),
        (1989, "平成", 1988),
        (1926, "昭和", 1925),
        (1912, "大正", 1911),
        (1868, "明治", 1867),
    )
    for start_year, era_name, offset in eras:
        if year >= start_year:
            era_year = year - offset
            era_year_label = "元" if era_year == 1 else str(era_year)
            return f"{era_name}{era_year_label.translate(_FULLWIDTH_DIGITS)}年度"
    return f"{str(year).translate(_FULLWIDTH_DIGITS)}年度"
