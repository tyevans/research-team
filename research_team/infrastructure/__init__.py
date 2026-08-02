"""The infrastructure layer: adapters for everything outside the process.

Implements the application's ports. Imports downward (domain, application
ports) and is imported only by composition and tests -- the use cases never
name anything in here.
"""
