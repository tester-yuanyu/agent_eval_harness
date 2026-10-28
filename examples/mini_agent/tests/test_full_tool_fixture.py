import pytest

from minimal_agent.runtime.tool_registry import InvalidToolArgumentsError


def query(registry, name, **values):
    model = registry.get(name).arguments_model
    arguments = {
        key: None
        for key, field in model.model_fields.items()
        if type(None) in getattr(field.annotation, "__args__", ())
    }
    return registry.invoke(name, {**arguments, **values})


def test_all_six_bindings_are_executable_and_separate_instances_are_isolated():
    from examples.full_tool_fixture import create_registry

    registry = create_registry()
    assert len(registry.definitions) == 6
    prepared = query(
        registry,
        "prepare_resource",
        resource_type="account",
        environment="test",
        count=2,
        request_id="r1",
    )
    assert prepared.success and len(prepared.data["resources"]) == 2
    found = query(
        registry,
        "query_information",
        resource_type="account",
        environment="test",
    )
    assert found.data["resources"] == prepared.data["resources"]
    assert (
        query(
            create_registry(),
            "query_information",
            resource_type="account",
            environment="test",
        ).code
        == "EMPTY"
    )
    repeated = query(
        registry,
        "prepare_resource",
        resource_type="account",
        environment="test",
        count=2,
        request_id="r1",
    )
    assert repeated.data == prepared.data
    assert (
        query(
            registry,
            "prepare_resource",
            resource_type="account",
            environment="test",
            count=3,
            request_id="r1",
        ).code
        == "CONFLICT"
    )


def test_queries_match_data_and_obey_and_mode_and_empty_semantics():
    from examples.full_tool_fixture import create_registry

    registry = create_registry()
    assert (
        query(registry, "query_user_info", user_id=10001).data["user"]["user_id"]
        == 10001
    )
    assert (
        query(registry, "query_user_info", user_id=10001, room_id=99999).code == "EMPTY"
    )
    gifts = query(registry, "query_gift_info", gift_ids=[101, 102])
    assert [x["gift_id"] for x in gifts.data["gifts"]] == [101, 102]
    assert query(registry, "query_gift_info", gift_ids=[101, 999]).code == "NOT_FOUND"
    assert (
        query(registry, "query_gift_info", gift_name="Rose").data["gifts"][0]["gift_id"]
        == 101
    )
    assert (
        query(registry, "query_pool_config", gift_id=101).data["pools"][0]["pool_id"]
        == 201
    )
    with pytest.raises(InvalidToolArgumentsError):
        query(registry, "query_pool_config", gift_id=101, pool_id=201)
    with pytest.raises(InvalidToolArgumentsError):
        query(registry, "query_user_info", phone="123")


def test_fixture_grant_requires_explicit_external_approval_and_is_atomic():
    from examples.full_tool_fixture import FixtureEnvironment

    environment = FixtureEnvironment()
    registry = environment.registry()
    arguments = dict(user_id=10001, gift_id=101, num=2, duration_days=7)
    assert (
        query(registry, "add_gift_to_backpack", **arguments).code
        == "CONFIRMATION_REQUIRED"
    )
    assert environment.grants == []
    environment.approve_next_grant()
    result = query(registry, "add_gift_to_backpack", **arguments)
    assert result.success
    assert environment.grants == result.data["grants"]
    assert (
        query(registry, "add_gift_to_backpack", **arguments).code
        == "CONFIRMATION_REQUIRED"
    )
    environment.approve_next_grant()
    assert (
        query(
            registry,
            "add_gift_to_backpack",
            user_ids=[10001, 99999],
            gift_id=101,
        ).code
        == "NOT_FOUND"
    )
    assert environment.grants == result.data["grants"]
