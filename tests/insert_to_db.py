from db.session import SessionLocal
from db.models import Measurement

with SessionLocal() as session:
    m = Measurement(time_end="2025-07-03 12:00", temperature_c=25)
    session.add(m)
    session.commit()
