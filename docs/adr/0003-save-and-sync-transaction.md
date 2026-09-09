# 保存并同步是一个事务

用户点一次「保存并同步」时，保存、同步、失败当场还原是同一个事务。HTTP 门口（`local_server`）不自己拍快照、不戳 git 私货。stash 隔离、只能 restore `stash@{0}`、先推再 CAS、同步不准改归档，仍看现有 merge_sync 契约。
