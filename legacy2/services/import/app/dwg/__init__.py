"""The drawing pipeline: DWG/DXF -> floors, rooms, openings -> 3D model.

Carried over from the single-application version (legacy/backend/dwg3d)
unchanged, so both versions recognise a drawing the same way; the code here
knows nothing about the service around it. Entry point: pipeline.run().
"""
