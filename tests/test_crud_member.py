"""MemberCRUD 단위 테스트"""
import pytest

from app.cruds.member import member_crud
from app.schemas.member import MemberCreate, MemberUpdate


class TestMemberCRUD:
    """MemberCRUD 기본 CRUD 테스트"""

    def _make_member_create(self, member_id="newuser", email="new@example.com"):
        return MemberCreate(
            name="새유저",
            member_id=member_id,
            email=email,
            password="Test1234!@",
            password_confirm="Test1234!@",
            phone="01012345678",
            role="user"
        )

    def test_create_member(self, db):
        """멤버 생성"""
        schema = self._make_member_create()
        member = member_crud.create_member(db, schema)

        assert member.member_id == "newuser"
        assert member.email == "new@example.com"
        assert member.role == "user"
        assert member.is_active is True
        # 비밀번호는 해시되어야 함
        assert member.password_hash != "Test1234!@"
        assert member.password_hash.startswith("$2b$")

    def test_get_member(self, db, sample_member):
        """멤버 조회"""
        found = member_crud.get_member(db, sample_member.member_id)
        assert found is not None
        assert found.member_id == sample_member.member_id

    def test_get_member_not_found(self, db):
        """존재하지 않는 멤버 조회"""
        found = member_crud.get_member(db, "nonexistent")
        assert found is None

    def test_get_member_inactive_excluded(self, db):
        """비활성 멤버는 기본 조회에서 제외"""
        schema = self._make_member_create(member_id="inactive-user", email="inactive@test.com")
        member = member_crud.create_member(db, schema)
        member.is_active = False
        db.flush()

        # 기본 조회: 제외
        assert member_crud.get_member(db, "inactive-user") is None
        # include_inactive=True: 포함
        assert member_crud.get_member(db, "inactive-user", include_inactive=True) is not None

    def test_get_member_by_email(self, db, sample_member):
        """이메일로 멤버 조회"""
        found = member_crud.get_member_by_email(db, sample_member.email)
        assert found is not None
        assert found.member_id == sample_member.member_id

    def test_password_hash_and_verify(self, db):
        """비밀번호 해싱 및 검증"""
        plain = "MyPassword123!"
        hashed = member_crud.get_password_hash(plain)

        assert hashed != plain
        assert member_crud.verify_password(plain, hashed) is True
        assert member_crud.verify_password("WrongPassword", hashed) is False

    def test_get_members_pagination(self, db):
        """멤버 목록 페이지네이션"""
        for i in range(5):
            schema = self._make_member_create(
                member_id=f"user-{i:03d}",
                email=f"user{i}@test.com"
            )
            member_crud.create_member(db, schema)

        members, total = member_crud.get_members(db, skip=0, limit=3)
        assert total == 5
        assert len(members) == 3

        members2, _ = member_crud.get_members(db, skip=3, limit=3)
        assert len(members2) == 2

    def test_get_members_search(self, db):
        """멤버 검색"""
        schema = self._make_member_create(member_id="search-target", email="target@test.com")
        member = member_crud.create_member(db, schema)
        member.name = "홍길동"
        db.flush()

        # 이름으로 검색 (SQLite에서는 LIKE로 동작)
        members, total = member_crud.get_members(db, search="홍길동")
        assert total >= 1

    def test_get_members_role_filter(self, db, sample_member, admin_member):
        """역할 필터"""
        members, total = member_crud.get_members(db, role="admin")
        assert all(m.role == "admin" for m in members)

    def test_update_member(self, db, sample_member):
        """멤버 정보 수정"""
        update = MemberUpdate(name="수정된이름", phone="010-9999-9999")
        updated = member_crud.update_member(db, sample_member.member_id, update)

        assert updated is not None
        assert updated.name == "수정된이름"
        assert updated.phone == "010-9999-9999"

    def test_update_member_password(self, db):
        """비밀번호 수정"""
        schema = self._make_member_create(member_id="pw-change", email="pw@test.com")
        member = member_crud.create_member(db, schema)
        old_hash = member.password_hash

        update = MemberUpdate(password="NewPass456!@")
        updated = member_crud.update_member(db, "pw-change", update)

        assert updated.password_hash != old_hash
        assert member_crud.verify_password("NewPass456!@", updated.password_hash) is True

    def test_update_last_login(self, db, sample_member):
        """마지막 로그인 시간 업데이트"""
        assert sample_member.last_login is None
        updated = member_crud.update_last_login(db, sample_member.member_id)
        assert updated.last_login is not None

    def test_delete_member(self, db):
        """멤버 삭제"""
        schema = self._make_member_create(member_id="to-delete", email="delete@test.com")
        member_crud.create_member(db, schema)

        result = member_crud.delete_member(db, "to-delete")
        assert result is True
        assert member_crud.get_member(db, "to-delete") is None

    def test_delete_member_not_found(self, db):
        """존재하지 않는 멤버 삭제"""
        result = member_crud.delete_member(db, "nonexistent")
        assert result is False
