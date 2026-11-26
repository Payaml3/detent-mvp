INK='currentColor'; OR='#FF4A1F'
def mark(key, ink=INK, orange=OR):
    if key=='A':  # Sieve: three, then two, through the rule, one settles
        return (f'<g fill="{ink}"><circle cx="9" cy="7.5" r="4"/><circle cx="24" cy="7.5" r="4"/><circle cx="39" cy="7.5" r="4"/>'
                f'<circle cx="16.5" cy="19" r="4"/><circle cx="31.5" cy="19" r="4"/>'
                f'<rect x="4" y="27" width="40" height="4" rx="0"/></g>'
                f'<circle cx="24" cy="40" r="6" fill="{orange}"/>')
    if key=='B':  # Settled D: a D whose counter holds one settled point
        return (f'<path fill="{ink}" fill-rule="evenodd" d="M5 4H23A20 20 0 0 1 23 44H5Z M13 12V36H23A12 12 0 0 0 23 12Z"/>'
                f'<circle cx="22" cy="30.5" r="5.5" fill="{orange}"/>')
    if key=='C':  # Three rules: decision, orchestration, operations narrow to one outcome
        return (f'<g fill="{ink}"><rect x="4" y="6" width="40" height="5"/><rect x="11" y="16" width="26" height="5"/>'
                f'<rect x="18" y="26" width="12" height="5"/></g>'
                f'<circle cx="24" cy="40" r="5.5" fill="{orange}"/>')
def svg(key, px=None, ink=INK, orange=OR, bg=None, pad=0):
    vb=f'{-pad} {-pad} {48+2*pad} {48+2*pad}'
    size=f' width="{px}" height="{px}"' if px else ''
    b=f'<rect x="{-pad}" y="{-pad}" width="{48+2*pad}" height="{48+2*pad}" fill="{bg}"/>' if bg else ''
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb}"{size}>{b}{mark(key,ink,orange)}</svg>'
