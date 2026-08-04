# Backend boundary (owned by World Model in the 9-person plan)

P0 is SQLite plus a thin FastAPI read API. Do not create a second WorldState here. The initial `SQLiteEventStore` lives in `services/world_model/` until this service needs to be split by evidence.
