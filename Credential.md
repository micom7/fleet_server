DataBase
CREATE USER fleet_app WITH PASSWORD 'devpassword';
CREATE DATABASE fleet OWNER fleet_app;
GRANT ALL PRIVILEGES ON DATABASE fleet TO fleet_app;