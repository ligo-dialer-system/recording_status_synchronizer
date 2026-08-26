def parse_line(linha):
    return dict(
        map(str.strip, sub.split('=', 1))
        for sub in linha.split(';')
        if '=' in sub
    )


def build_line(fields):
    return ';'.join(f"{k}={v}" for k, v in fields.items() if v is not None) + "\n"
