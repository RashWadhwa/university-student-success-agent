SELECT 'CREATE DATABASE student_success_test'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'student_success_test')\gexec
