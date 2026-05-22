-- Emerald Neo4j initialisation script
-- Run once when setting up a fresh Neo4j instance.

-- Entity constraints
CREATE CONSTRAINT entity_id_unique IF NOT EXISTS FOR (e:Entity) REQUIRE e.id IS UNIQUE;
CREATE CONSTRAINT entity_external_idx IF NOT EXISTS FOR (e:Entity) REQUIRE (e.external_id, e.type) IS NODE KEY;

-- Memory constraints
CREATE CONSTRAINT memory_id_unique IF NOT EXISTS FOR (m:Memory) REQUIRE m.id IS UNIQUE;

-- Document constraints
CREATE CONSTRAINT document_id_unique IF NOT EXISTS FOR (d:Document) REQUIRE d.id IS UNIQUE;

-- Chunk constraints
CREATE CONSTRAINT chunk_id_unique IF NOT EXISTS FOR (c:Chunk) REQUIRE c.id IS UNIQUE;

-- Memory indexes
CREATE INDEX memory_entity IF NOT EXISTS FOR (m:Memory) ON (m.is_latest, m.memory_type);
CREATE INDEX memory_temporal IF NOT EXISTS FOR (m:Memory) ON (m.valid_until);
CREATE INDEX memory_expired IF NOT EXISTS FOR (m:Memory) ON (m.expired_at);

-- Entity indexes
CREATE INDEX entity_external_id IF NOT EXISTS FOR (e:Entity) ON (e.external_id);
